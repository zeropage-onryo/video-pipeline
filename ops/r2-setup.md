# Turning on Cloudflare R2 (fixes blank images on the deployed site)

Why: reference photos (characters/props/locations) and generated renders
are currently saved to local disk on whichever machine made them. The
deployed Fly app reads the same shared Postgres database but has its own,
separate disk -- so it sees the right counts and captions but can't find
the actual image files. Turning on R2 gives every image a real public URL
the moment it's created, on any machine, so the deployed site (and your
Mac) both just load the same URL.

## 1. Create the bucket (Cloudflare dashboard)

1. cloudflare.com -> your account -> R2 Object Storage -> Create bucket.
2. Name it something like `zeropage-media`. Region: Automatic.
3. Open the bucket -> Settings -> Public Access -> enable the r2.dev
   public bucket URL (or attach a custom domain if you have one you'd
   rather use). Copy that public URL -- it's `R2_PUBLIC_BASE_URL` below.

## 2. Create API credentials

1. R2 -> Manage R2 API Tokens -> Create API Token.
2. Permissions: Object Read & Write. Scope it to the one bucket above.
3. Copy the Access Key ID and Secret Access Key it shows you -- the
   secret is only shown once.
4. Your Account ID is in the right sidebar of the R2 overview page (or
   Cloudflare dashboard home).

## 3. Set the five env vars

Add to your local `.env` (never commit this file):

```
R2_ACCOUNT_ID=<account id from step 2.4>
R2_ACCESS_KEY_ID=<access key from step 2.3>
R2_SECRET_ACCESS_KEY=<secret key from step 2.3>
R2_BUCKET=zeropage-media
R2_PUBLIC_BASE_URL=https://pub-xxxxxxxx.r2.dev
```

Then set the same five as Fly secrets so the deployed app can see them
too (run from your Mac, where `flyctl` is already logged in):

```
fly secrets set \
  R2_ACCOUNT_ID=<value> \
  R2_ACCESS_KEY_ID=<value> \
  R2_SECRET_ACCESS_KEY=<value> \
  R2_BUCKET=zeropage-media \
  R2_PUBLIC_BASE_URL=https://pub-xxxxxxxx.r2.dev
```

`fly secrets set` restarts the app automatically to pick them up.

## 4. Backfill what already exists

Once the five vars are in your local `.env`, run these two scripts once
from the project root (they're safe to re-run -- both skip anything
already uploaded):

```
python3 ops/backfill_reference_photos_r2.py
python3 ops/backfill_renders_r2.py
```

The first pushes every photo under `characters/`, `props/`, and
`locations/` up to R2. The second finds every generated-asset row still
pointing at a local `/renders/...` path, uploads that file, and updates
the database row to the new public URL. Both print a summary of what
they did and skipped.

## 5. What changed in code (already done)

- `src/storage.py`: added `url_for_key()` -- builds a public URL for a
  key without uploading, for photos already known to be in the bucket.
- `src/asset_shelf.py`: `photo_url()` now returns the R2 URL when R2 is
  configured, instead of the local `/characters/.../photo/...` route --
  same fallback route still works when R2 isn't set (local dev).
- `app/api.py`: the two upload handlers (`asset_create_location`,
  `_create_entity` for characters/props) now push each newly-saved photo
  to R2 right after writing it to disk, best-effort -- a storage hiccup
  never blocks the upload, it just leaves that one photo on the local
  fallback route until the next backfill run.
- `src/render_assets.py`: added `update_media_url()`, used by the
  backfill script to repoint old local render URLs at R2 after upload.

Nothing above requires R2 to be configured to keep working as before --
every new call checks `storage.configured()` first and quietly falls
back to the existing local-path behavior when it's not set.

---

# Multi-tenant media: the key scheme, thumbnails, signing, tiering

Everything above describes the FLAT scheme -- one global key per object,
a public bucket, and a `pub-<hash>.r2.dev` URL stored on the row. That
was right for one person. It does not survive a second account:

- `characters/michael/IMG_1.jpg` is the same key for every account, so
  the second studio to upload a character called `michael` overwrote the
  first one's face.
- Nothing in a key says who owns it, so per-account accounting, quota
  and deletion are all impossible.
- A public bucket with guessable keys means anyone who guesses a URL
  reads anybody's unreleased footage.
- Nothing ever ages out, and every Queue card draws four full-size
  iPhone JPEGs -- 18MB to show four thumbnails, on a phone.

`src/media.py` is the one owner of the fix. `ZEROPAGE_MEDIA` is the one
switch, and it is a LADDER -- each rung is a superset of the one below,
and every rung is reversible by setting the variable back:

    legacy   (default)  flat keys, public URLs. Today's behaviour, byte
                        for byte.
    tenant              m/<account>/<tail> keys, public URLs.
    signed              the same keys, presigned URLs, bucket private.

## Climbing to `tenant`

1. **Copy the existing objects across.** New writes go to the new keys
   the moment the rung changes; everything already in the bucket is on
   the flat key, so flipping first gives you a studio full of empty
   tiles.

   ```
   venv/bin/python -m ops.migrate_media_keys              # report only
   venv/bin/python -m ops.migrate_media_keys --write --thumbs
   ```

   It COPIES -- the old keys stay, still public, still serving -- so it
   is re-runnable, safe to interrupt, and the flip is reversible.

   **The bin is shared.** `refs/` goes to `m/shared/refs/...` with no ownership lookup at
   all: a composer upload and a crawled image are deliberately the same shape, and `scout_bin`
   has no account column, so nothing at read time can tell them apart. Everything else —
   characters, props, locations, renders, soul-training — is fenced per account.

   Read the report before writing. A flat key does not say who owns it,
   so ownership is recovered from the database; anything it cannot
   attribute is listed and left alone rather than guessed. Two accounts
   holding the same slug are reported as **ambiguous**: under the flat
   scheme one of them overwrote the other and nobody can now say which
   bytes survived. The honest repair is to re-upload from the account
   that owns the photo.

2. **Flip it.** Locally in `.env`, and as a Fly secret:

   ```
   ZEROPAGE_MEDIA=tenant
   fly secrets set ZEROPAGE_MEDIA=tenant
   ```

   Rows do not need rewriting. `asset_shelf.parse_ref` reads the logical
   name, the legacy absolute URL and the new one, and `media.url_for`
   mints from any of them -- which is what makes both directions safe.

## Climbing to `signed`

3. **Put the bucket on the custom domain** (R2 -> the bucket ->
   Settings -> Custom Domains). `pub-<hash>.r2.dev` is rate-limited and
   Cloudflare calls it development-only: no cache, no WAF, no access
   rules. Set `R2_PUBLIC_BASE_URL` to the custom domain, both locally
   and as a Fly secret.

4. **Turn off public access** on the bucket, then:

   ```
   ZEROPAGE_MEDIA=signed
   ```

   Every media URL is now a presigned GET, minted per read and good for
   two hours, with the signature reused inside each hour so a browser
   still gets cache hits on a card it has already drawn.

   **Know what this costs.** A presigned URL has to address the S3 API
   endpoint, because an R2 custom domain serves the public bucket path
   and will not accept a SigV4 query signature. So `signed` trades the
   Cloudflare cache in front of the custom domain for real per-tenant
   access control, and origin reads go up. At current volume that is
   pennies of Class B operations; if it ever shows up in the bill, the
   way to get both is a Worker on the custom domain validating a token
   against an R2 binding -- infrastructure, not Python, and deliberately
   not built until there is a number saying it is needed.

## Tiering

```
venv/bin/python -m ops.media_lifecycle            # show what is set
venv/bin/python -m ops.media_lifecycle --write
```

**This one needs an ADMIN token.** Lifecycle is a bucket-level operation and the token from
step 2 is scoped to Object Read & Write, which is right for everything else this repo does. The
script refuses with an explanation and changes nothing; either add the rules by hand in the
dashboard (R2 -> the bucket -> Settings -> Object lifecycle rules) or mint a second token with
Admin Read & Write for the one run.

Masters move to Infrequent Access after 30 days (two thirds the storage
price, a per-GB charge on the way back out). Thumbnails under `t/` are
deliberately left in Standard -- they are what every card reads, and a
retrieval fee on the most-read object is the tiering decision made
backwards. Nothing expires and nothing is deleted: archiving never
deletes, and tiering is how that promise gets kept without per-account
bytes growing forever.

## Thumbnails

`src/media.mirror` writes the 480px derivative beside every photo it
mirrors, under `t/<account>/<same tail>`. `_assets_all` serves them as
`photo_thumbs` and uses one as the `poster`.

`refs` and `photo_thumbs` are deliberately NOT one list. `refs[0]` is
the single frame Runway anchors a clip on, and anchoring a clip on a
480px thumbnail is exactly the kind of quiet downgrade this reference
layer keeps being bitten by. A card with no derivative to point at falls
back to `?thumb=1`, the local handler that has always done this off
disk: a slow tile, never a missing one.
