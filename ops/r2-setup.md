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
