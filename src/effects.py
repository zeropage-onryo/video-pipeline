"""
Effects: the fal endpoints that CHANGE something that already exists --
an image edited by a prompt, a still turned into a template effect or a
camera move, a clip upscaled, smoothed or given sound (2026-10-07).

Mike's call: the zeropage MCP is for working with Claude on images, video
and effects, every one of them quoted first and spent only after a yes in
chat. `generate_image` / `generate_video` make something from a prompt;
this module is the third door, and it is shaped exactly like
`fal.generate_image_from_prompt`, the composer's still: a cap check, a
CREDIT HOLD at the approved price before the submit, the generations
row, settle, the Assets wall.

WHY A TABLE AND NOT A PASSTHROUGH. Every endpoint below names its input
differently (`image_url`, `image_urls`, `input_image_urls`, `video_url`)
and prices differently (per image, per second, per second by resolution,
per second of the SOURCE clip). An agent handed "any fal endpoint, any
body" would guess both. So each row says, in its own words, the field it
takes, the options it allows (and REFUSES anything else, never clamps),
and how its price is computed -- dated, with the page it was read off.
Re-check a row before trusting it; fal changes these.

Verified 2026-10-07 against each endpoint's OpenAPI schema
(fal.ai/api/openapi/queue/openapi.json?endpoint_id=<id>) and the price on
its model page. Left OUT because a price or input could not be verified:
lip sync (needs an audio input this studio has no id for yet), relight
(iclight-v2 price unpublished -- use an image edit with a lighting
prompt), RIFE/FILM interpolation (billed per compute second, so there is
no price to quote -- Topaz's target_fps does the same job at a known
rate), PixVerse at 8s (no published 8s price).
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from . import charge as charging
from . import fal, generative, ledger

CHECKED = "2026-10-07"
LOG_TOOL = fal.IMAGE_LOG_TOOL          # "fal": effects count with the stills
CATEGORIES = ("image_edit", "video_effect", "camera", "finish")


# --- the enums, copied off the schemas on CHECKED --------------------------
# Long lists, kept verbatim: an effect name is a wire value, and a name
# this table does not carry is refused before anything is held.
KLING_EFFECTS = (
    "heart_gesture",
    "bullet_time_360",
    "day_to_night",
    "swish_swish",
    "running_man",
    "swing_swing",
    "skateskate",
    "building_sweater",
    "pure_white_wings",
    "black_wings",
    "golden_wing",
    "pink_pink_wings",
    "countdown_teleport",
    "instant_christmas",
    "birthday_star",
    "tiger_hug_pro",
    "pet_lion_pro",
    "guardian_spirit",
    "drunk_dance",
    "drunk_dance_pet",
    "daoma_dance",
    "bouncy_dance",
    "smooth_sailing_dance",
    "new_year_greeting",
    "lion_dance",
    "prosperity",
    "great_success",
    "golden_horse_fortune",
    "red_packet_box",
    "lucky_horse_year",
    "lucky_red_packet",
    "lucky_money_come",
    "lion_dance_pet",
    "dumpling_making_pet",
    "fish_making_pet",
    "pet_red_packet",
    "lantern_glow",
    "expression_challenge",
    "overdrive",
    "heart_gesture_dance",
    "poping",
    "martial_arts",
    "running",
    "nezha",
    "motorcycle_dance",
    "subject_3_dance",
    "ghost_step_dance",
    "phantom_jewel",
    "zoom_out",
    "cheers_2026",
    "kiss_pro",
    "fight_pro",
    "hug_pro",
    "heart_gesture_pro",
    "dollar_rain_pro",
    "pet_bee_pro",
    "santa_random_surprise",
    "magic_match_tree",
    "happy_birthday",
    "thumbs_up_pro",
    "surprise_bouquet",
    "bouquet_drop",
    "glamour_photo_shoot",
    "box_of_joy",
    "first_toast_of_the_year",
    "my_santa_pic",
    "santa_gift",
    "steampunk_christmas",
    "snowglobe",
    "christmas_photo_shoot",
    "ornament_crash",
    "santa_express",
    "coronation_of_frost",
    "spark_in_the_snow",
    "scarlet_and_snow",
    "bullet_time_lite",
    "jumping_ginger_joy",
    "venomous_spider",
    "throne_of_king",
    "luminous_elf",
    "woodland_elf",
    "snowboarding",
    "witch_transform",
    "vampire_transform",
    "pumpkin_head_transform",
    "demon_transform",
    "mummy_transform",
    "zombie_transform",
    "cute_pumpkin_transform",
    "halloween_escape",
    "korean_baseball",
    "pet_moto_rider",
    "3d_cartoon_2",
    "girlfriend",
    "boyfriend",
    "pet_dance",
    "splashsplash",
    "surfsurf",
)
PIXVERSE_EFFECTS = (
    "Kiss Me AI",
    "Kiss",
    "Muscle Surge",
    "Warmth of Jesus",
    "Anything, Robot",
    "The Tiger Touch",
    "Hug",
    "Holy Wings",
    "Microwave",
    "Zombie Mode",
    "Squid Game",
    "Baby Face",
    "Black Myth: Wukong",
    "Long Hair Magic",
    "Leggy Run",
    "Fin-tastic Mermaid",
    "Punch Face",
    "Creepy Devil Smile",
    "Thunder God",
    "Eye Zoom Challenge",
    "Who's Arrested?",
    "Baby Arrived",
    "Werewolf Rage",
    "Bald Swipe",
    "BOOM DROP",
    "Huge Cutie",
    "Liquid Metal",
    "Sharksnap!",
    "Dust Me Away",
    "3D Figurine Factor",
    "Bikini Up",
    "My Girlfriends",
    "My Boyfriends",
    "Subject 3 Fever",
    "Earth Zoom",
    "Pole Dance",
    "Vroom Dance",
    "GhostFace Terror",
    "Dragon Evoker",
    "Skeletal Bae",
    "Summoning succubus",
    "Halloween Voodoo Doll",
    "3D Naked-Eye AD",
    "Package Explosion",
    "Dishes Served",
    "Ocean ad",
    "Supermarket AD",
    "Tree doll",
    "Come Feel My Abs",
    "The Bicep Flex",
    "London Elite Vibe",
    "Flora Nymph Gown",
    "Christmas Costume",
    "It's Snowy",
    "Reindeer Cruiser",
    "Snow Globe Maker",
    "Pet Christmas Outfit",
    "Adopt a Polar Pal",
    "Cat Christmas Box",
    "Starlight Gift Box",
    "Xmas Poster",
    "Pet Christmas Tree",
    "City Santa Hat",
    "Stocking Sweetie",
    "Christmas Night",
    "Xmas Front Page Karma",
    "Grinch's Xmas Hijack",
    "Giant Product",
    "Truck Fashion Shoot",
    "Beach AD",
    "Shoal Surround",
    "Mechanical Assembly",
    "Lighting AD",
    "Billboard AD",
    "Product close-up",
    "Parachute Delivery",
    "Dreamlike Cloud",
    "Macaron Machine",
    "Poster AD",
    "Truck AD",
    "Graffiti AD",
    "3D Figurine Factory",
    "The Exclusive First Class",
    "Art Zoom Challenge",
    "I Quit",
    "Hitchcock Dolly Zoom",
    "Smell the Lens",
    "I believe I can fly",
    "Strikout Dance",
    "Courtside Cam",
    "Pit Crew Moment",
    "K-Baseball Sprint",
    "Toddler Doodle",
    "Idol Ending",
    "Apex Dance",
    "OmniHero Forge",
    "Palm Decode",
    "The Age Ripple",
    "My Future Is Limitless",
    "Knee Slide",
    "Epic Goal Save",
    "Sideline Ball Boy",
    "Cup Celebration",
    "Victory Roar",
    "Vuvuzela Fan",
    "World Champion Lift",
    "Tunnel to Captain",
    "Liquid Soccer Morph",
    "Jump Into Crowd 2",
    "Golden Pitch Crasher",
    "Stadium Fan Cam",
    "Broadcast Moto GP",
    "The Grotesque Clay",
    "Rookie Star Card",
    "The Final Hug",
    "Sharp Post-Match Comment",
    "Street Maverick",
    "Pitch Legend",
    "One Step At A Time",
    "Birthday Mirror",
    "Superstar Lobby",
    "Final Battle Room",
    "Top of the World",
    "Mini Me Unboxed",
    "WonderPOP Surprise",
    "White Chicks",
    "Kiss me",
    "What a Day",
    "The Last Leap at Sunset",
    "Tiny Sticker Chef Chaos",
    "Mini Squeeze Toy",
    "Tearful Gunman",
    "Street Fashion Caricature",
    "Mini Me Makeover",
    "Street Art Awakening",
    "Hug Together",
    "ACAI dance Duet",
    "PUBG Winner Hit!",
    "Blocky Mini-Me",
    "Cheat Day Busted",
    "MiniSocial Recharge",
    "My Little Perler Charm",
    "Where did this cobweb come from?",
    "Holy Beast Summoning Technique",
    "IT'S THE FIRST OF THE MONTH",
    "Pet Editorial",
    "Three lifetime bond",
    "Pixel World",
    "Mint in Box",
    "Hands up, Hand",
    "Flora Nymph Go",
    "Somber Embrace",
    "Beam me up",
    "Suit Swagger",
)
CAMERA_MOVES = (
    "horizontal_left",
    "horizontal_right",
    "vertical_up",
    "vertical_down",
    "zoom_in",
    "zoom_out",
    "crane_up",
    "quickly_zoom_in",
    "quickly_zoom_out",
    "smooth_zoom_in",
    "camera_rotation",
    "robo_arm",
    "super_dolly_out",
    "whip_pan",
    "hitchcock",
    "left_follow",
    "right_follow",
    "pan_left",
    "pan_right",
    "fix_bg",
)
PIXVERSE_RES = ("360p", "540p", "720p", "1080p")
# PixVerse's published price is for a 5s clip; 8s exists on the wire but
# has no published price, so it is not offered.
PIXVERSE_5S_USD = {"360p": 0.15, "540p": 0.15, "720p": 0.20, "1080p": 0.40}
NANO_EDIT_ASPECTS = ("auto", "21:9", "16:9", "3:2", "4:3", "5:4", "1:1",
                     "4:5", "3:4", "2:3", "9:16")
KONTEXT_ASPECTS = ("21:9", "16:9", "4:3", "3:2", "1:1", "2:3", "3:4", "9:16", "9:21")


def _topaz_usd(opts: dict, probe: dict) -> float:
    """$/s of the SOURCE by OUTPUT height: up to 720p $0.01, to 1080p
    $0.02, above $0.08; doubled at 60fps output (fal's page, CHECKED).
    Read as: anything above 30fps out is billed as 60."""
    out_h = probe["height"] * int(opts["upscale_factor"])
    rate = 0.01 if out_h <= 720 else 0.02 if out_h <= 1080 else 0.08
    fps = opts.get("target_fps") or probe.get("fps") or 30
    if float(fps) > 30:
        rate *= 2
    return probe["seconds"] * rate


def _sound_seconds(probe: dict) -> int:
    return max(1, min(30, int(-(-probe["seconds"] // 1))))


EFFECTS: dict[str, dict] = {
    # -- image edits: an image in, an image out --------------------------
    "nano-banana-edit": {
        "label": "Nano Banana edit", "category": "image_edit",
        "note": "edit by instruction; keeps faces and identity; up to 4 images in",
        "endpoint": "fal-ai/nano-banana/edit", "takes": "image",
        "field": "image_urls", "as_list": True, "sources": (1, 4),
        "prompt": "required", "output": "image",
        "options": {"aspect_ratio": {"values": NANO_EDIT_ASPECTS, "default": "auto"}},
        "fixed": {"num_images": 1},
        "price": lambda o, p: 0.039,
        "source": "https://fal.ai/models/fal-ai/nano-banana/edit",
    },
    "flux-kontext-pro": {
        "label": "FLUX Kontext Pro", "category": "image_edit",
        "note": "precise local edits: swap an object, change text, restyle",
        "endpoint": "fal-ai/flux-pro/kontext", "takes": "image",
        "field": "image_url", "as_list": False, "sources": (1, 1),
        "prompt": "required", "output": "image",
        "options": {"aspect_ratio": {"values": KONTEXT_ASPECTS, "default": None}},
        "fixed": {"num_images": 1},
        "price": lambda o, p: 0.04,
        "source": "https://fal.ai/models/fal-ai/flux-pro/kontext",
    },
    "seedream-edit": {
        "label": "Seedream 4 edit", "category": "image_edit",
        "note": "ByteDance; multi-image composites, cheap",
        "endpoint": "fal-ai/bytedance/seedream/v4/edit", "takes": "image",
        "field": "image_urls", "as_list": True, "sources": (1, 4),
        "prompt": "required", "output": "image",
        "options": {}, "fixed": {"num_images": 1},
        "price": lambda o, p: 0.03,
        "source": "https://fal.ai/models/fal-ai/bytedance/seedream/v4/edit",
    },
    "remove-background": {
        "label": "Remove background", "category": "image_edit",
        "note": "Bria RMBG 2.0; transparent PNG; no prompt",
        "endpoint": "fal-ai/bria/background/remove", "takes": "image",
        "field": "image_url", "as_list": False, "sources": (1, 1),
        "prompt": "none", "output": "image", "options": {}, "fixed": {},
        "price": lambda o, p: 0.018,
        "source": "https://fal.ai/models/fal-ai/bria/background/remove",
    },
    # -- template effects: a still in, a styled clip out ------------------
    "kling-effect": {
        "label": "Kling effects", "category": "video_effect",
        "note": "98 one-click templates on a still (heart_gesture takes 2 images)",
        "endpoint": "fal-ai/kling-video/v1.6/standard/effects", "takes": "image",
        "field": "input_image_urls", "as_list": True, "sources": (1, 2),
        "prompt": "none", "output": "video",
        "options": {"effect_scene": {"values": KLING_EFFECTS, "required": True},
                    "duration": {"values": ("5", "10"), "default": "5"}},
        "fixed": {},
        "price": lambda o, p: 0.056 * int(o["duration"]),
        "source": "https://fal.ai/models/fal-ai/kling-video/v1.6/standard/effects",
    },
    "pixverse-effect": {
        "label": "PixVerse effects", "category": "video_effect",
        "note": "154 templates on a still (v5), 5s",
        "endpoint": "fal-ai/pixverse/v5/effects", "takes": "image",
        "field": "image_url", "as_list": False, "sources": (1, 1),
        "prompt": "none", "output": "video",
        "options": {"effect": {"values": PIXVERSE_EFFECTS, "required": True},
                    "resolution": {"values": PIXVERSE_RES, "default": "720p"},
                    "duration": {"values": ("5",), "default": "5"}},
        "fixed": {},
        "price": lambda o, p: PIXVERSE_5S_USD[o["resolution"]],
        "source": "https://fal.ai/models/fal-ai/pixverse/v5/effects",
    },
    # -- camera moves: a still in, a clip with a named move out ------------
    "camera-move": {
        "label": "Camera move (PixVerse 4.5)", "category": "camera",
        "note": ("a named camera move on a still, 5s. Other video models take "
                 "the move in the prompt instead (prompt_craft)"),
        "endpoint": "fal-ai/pixverse/v4.5/image-to-video", "takes": "image",
        "field": "image_url", "as_list": False, "sources": (1, 1),
        "prompt": "required", "output": "video",
        "options": {"camera_movement": {"values": CAMERA_MOVES, "required": True},
                    "resolution": {"values": PIXVERSE_RES, "default": "720p"},
                    "style": {"values": ("anime", "3d_animation", "clay", "comic",
                                         "cyberpunk"), "default": None},
                    "duration": {"values": ("5",), "default": "5"}},
        "fixed": {},
        "price": lambda o, p: PIXVERSE_5S_USD[o["resolution"]],
        "source": "https://fal.ai/models/fal-ai/pixverse/v4.5/image-to-video",
    },
    # -- finishing: a clip in, a better clip out ---------------------------
    "upscale": {
        "label": "Upscale / smooth (Topaz)", "category": "finish",
        "note": ("2x upscale; target_fps interpolates (24/30/60 -- 60 is slow-mo "
                 "ready and costs double); upscale_factor 1 + target_fps = smooth only"),
        "endpoint": "fal-ai/topaz/upscale/video", "takes": "video",
        "field": "video_url", "as_list": False, "sources": (1, 1),
        "prompt": "none", "output": "video",
        "options": {"upscale_factor": {"values": (1, 2), "default": 2},
                    "target_fps": {"values": (24, 30, 60), "default": None}},
        "fixed": {"H264_output": True},
        "price": _topaz_usd, "probe": True,
        "source": "https://fal.ai/models/fal-ai/topaz/upscale/video",
    },
    "add-sound": {
        "label": "Add sound (MMAudio)", "category": "finish",
        "note": "sound effects/ambience generated to the picture; prompt = what it sounds like; clips up to 30s",
        "endpoint": "fal-ai/mmaudio-v2", "takes": "video",
        "field": "video_url", "as_list": False, "sources": (1, 1),
        "prompt": "required", "output": "video", "options": {}, "fixed": {},
        "price": lambda o, p: 0.001 * _sound_seconds(p), "probe": True,
        "max_seconds": 30,
        "source": "https://fal.ai/models/fal-ai/mmaudio-v2",
    },
}
EFFECT_NAMES = tuple(EFFECTS)
SAMPLE = 12       # enum values shown per option in the summary listing


def spec(effect: str) -> dict:
    row = EFFECTS.get((effect or "").strip())
    if row is None:
        raise ValueError(f"effect must be one of {list(EFFECT_NAMES)}, got {effect!r}")
    return row


def _option_view(opt: dict, full: bool) -> dict:
    values = list(opt["values"])
    view = {"default": opt.get("default"), "required": bool(opt.get("required")),
            "count": len(values)}
    view["values"] = values if full or len(values) <= SAMPLE else values[:SAMPLE]
    if not full and len(values) > SAMPLE:
        view["more"] = f"{len(values) - SAMPLE} more -- effects(effect='<id>') lists them all"
    return view


def catalogue(effect: str = "", category: str = "") -> list[dict]:
    """The menu the MCP shows. A projection of EFFECTS, so it cannot list
    something run() would refuse."""
    if effect:
        names = [spec(effect) and effect.strip()]
    else:
        if category and category not in CATEGORIES:
            raise ValueError(f"category must be one of {list(CATEGORIES)}, got {category!r}")
        names = [k for k, v in EFFECTS.items() if not category or v["category"] == category]
    rows = []
    for name in names:
        row = EFFECTS[name]
        lo, hi = row["sources"]
        rows.append({
            "id": name, "label": row["label"], "category": row["category"],
            "note": row["note"], "takes": row["takes"], "output": row["output"],
            "sources": {"min": lo, "max": hi}, "prompt": row["prompt"],
            "options": {k: _option_view(v, bool(effect)) for k, v in row["options"].items()},
            "pricing": _pricing_note(name), "checked": CHECKED, "page": row["source"],
        })
    return rows


def _pricing_note(name: str) -> str:
    notes = {
        "kling-effect": "$0.056 per second",
        "pixverse-effect": "5s clip: $0.15 at 360p/540p, $0.20 at 720p, $0.40 at 1080p",
        "camera-move": "5s clip: $0.15 at 360p/540p, $0.20 at 720p, $0.40 at 1080p",
        "upscale": ("per second of the source by output height: <=720p $0.01, "
                    "<=1080p $0.02, above $0.08; x2 above 30fps out"),
        "add-sound": "$0.001 per second of the clip",
    }
    if name in notes:
        return notes[name]
    return f"${EFFECTS[name]['price']({}, {})} per image"


def check_options(effect: str, options: Optional[dict]) -> dict:
    """The caller's options, resolved against the row's legal sets.
    Unknown names and illegal values are REFUSED with the legal set."""
    row = spec(effect)
    given = dict(options or {})
    unknown = sorted(set(given) - set(row["options"]))
    if unknown:
        raise ValueError(f"{row['label']} takes options {sorted(row['options']) or 'none'}, "
                         f"not {unknown}")
    out = {}
    for name, opt in row["options"].items():
        value = given.get(name, opt.get("default"))
        if value in (None, ""):
            if opt.get("required"):
                raise ValueError(f"{row['label']} needs `{name}` "
                                 f"(effects(effect='{effect}') lists the values)")
            continue
        legal = list(opt["values"])
        match = next((v for v in legal if str(v) == str(value)), None)
        if match is None:
            shown = legal if len(legal) <= 30 else legal[:30] + ["..."]
            raise ValueError(f"{row['label']}: {name}={value!r} is not one of {shown}")
        out[name] = match
    if effect == "upscale" and out.get("upscale_factor") == 1 and not out.get("target_fps"):
        raise ValueError("upscale_factor 1 changes nothing without target_fps")
    return out


def check_sources(effect: str, n: int, options: dict) -> None:
    row = spec(effect)
    lo, hi = row["sources"]
    if effect == "kling-effect":
        need = 2 if options.get("effect_scene") == "heart_gesture" else 1
        lo = hi = need
    if not lo <= n <= hi:
        want = f"exactly {lo}" if lo == hi else f"{lo} to {hi}"
        raise ValueError(f"{row['label']} takes {want} {row['takes']} source"
                         f"{'s' if hi != 1 else ''}, got {n}")


def check_prompt(effect: str, prompt: str) -> str:
    row = spec(effect)
    prompt = " ".join((prompt or "").split())
    if row["prompt"] == "required" and not prompt:
        raise ValueError(f"{row['label']} needs a prompt")
    if row["prompt"] == "none" and prompt:
        raise ValueError(f"{row['label']} takes no prompt -- leave it empty")
    return prompt


def probe_video(target: str) -> dict:
    """seconds / width / height / fps of a clip, by ffprobe (a local path or
    a URL). The price of a finishing pass is a function of these, so a clip
    that cannot be measured is refused, never guessed at."""
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height,r_frame_rate:format=duration",
             "-of", "json", str(target)],
            capture_output=True, text=True, timeout=60, check=True).stdout
        data = json.loads(out)
        stream = data["streams"][0]
        num, _, den = str(stream.get("r_frame_rate") or "0/1").partition("/")
        fps = float(num) / float(den or 1) if float(den or 1) else 0.0
        seconds = float(data["format"]["duration"])
        return {"seconds": round(seconds, 3), "width": int(stream["width"]),
                "height": int(stream["height"]), "fps": round(fps, 3)}
    except Exception as e:
        raise ValueError(f"could not measure the source clip ({type(e).__name__}); "
                         "a finishing pass is priced off its length and size") from e


def quote_usd(effect: str, options: dict, probe: Optional[dict] = None) -> float:
    row = spec(effect)
    if row.get("probe") and not probe:
        raise ValueError(f"{row['label']} is priced off the source clip; probe it first")
    if probe and row.get("max_seconds") and probe["seconds"] > row["max_seconds"]:
        raise ValueError(f"{row['label']} takes clips up to {row['max_seconds']}s, "
                         f"this one is {probe['seconds']}s")
    return round(float(row["price"](options, probe or {})), 4)


def build_body(effect: str, urls: list[str], prompt: str, options: dict,
               probe: Optional[dict] = None) -> tuple[str, dict]:
    row = spec(effect)
    body: dict = {**row["fixed"], **options}
    body[row["field"]] = list(urls) if row["as_list"] else urls[0]
    if prompt:
        body["prompt"] = prompt
    if effect == "add-sound":
        body["duration"] = _sound_seconds(probe or {"seconds": 8})
    return row["endpoint"], body


def fetchable_video(media_url: str, output_path: str = "", *,
                    account_id: Optional[int] = None) -> Optional[str]:
    """A clip as a URL fal's servers can fetch: a public URL as is, a local
    render uploaded to the bucket, else None (the caller refuses)."""
    from . import media, storage
    if media_url and media_url.startswith(("http://", "https://")):
        return media_url
    path = Path(output_path) if output_path else None
    if (path is None or not path.is_file()) and media_url and media_url.startswith("/renders/"):
        path = fal.RENDERS_ROOT / media_url[len("/renders/"):]
    if path is None or not path.is_file() or not storage.configured():
        return None
    digest = hashlib.sha256(path.read_bytes()).hexdigest()[:16]
    key = f"refs/fal/{digest}{path.suffix or '.mp4'}"
    try:
        return storage.upload_file(path, key=media.object_key(key, account_id),
                                   content_type="video/mp4")
    except Exception:
        return None


def _suffix(url: str, kind: str) -> str:
    tail = url.split("?", 1)[0].rsplit("/", 1)[-1]
    ext = Path(tail).suffix.lower()
    allowed = {".png", ".jpg", ".jpeg", ".webp"} if kind == "image" else {".mp4", ".mov", ".webm"}
    return ext if ext in allowed else (".png" if kind == "image" else ".mp4")


def run(effect: str, urls: list[str], prompt: str, options: dict, *,
        usd: float, sources: Optional[list] = None, probe: Optional[dict] = None,
        account_id: Optional[int] = None, db_path=None, http=None,
        source: str = "mcp", bank: bool = True,
        publish: Optional[Callable] = None,
        project_id: Optional[int] = None) -> dict[str, Any]:
    """Never raises: {"ok", "media_url", "generation_id", "asset_id", "path",
    "error"}. The caller has already checked everything above and had the
    price approved; `usd` is that approved price, and it is what is held."""
    from . import render_assets
    kwargs = {"dsn": db_path} if db_path is not None else {}
    try:
        row = spec(effect)
        if not fal.has_key(account_id):
            return {"ok": False, "error": "no fal key -- set FAL_KEY for the installation"}
        generative.init(**kwargs)
        # the image door's own wall: an effect is counted under the image
        # tool name, so it shares the stills' count and never a clip's
        refusal = generative.cap_error(
            LOG_TOOL, 1, account_id=account_id,
            per_account=fal.DAILY_CAP, ceiling=fal.GLOBAL_DAILY_CAP,
            dsn=db_path, env_prefix="FAL", phrase="images generated")
        if refusal:
            return {"ok": False, "error": refusal}
        endpoint, body = build_body(effect, urls, prompt, options, probe)
        if "prompt" in body:
            body["prompt"] = fal.safe_prompt(body["prompt"], db_path, account_id)

        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        out_stub = fal.RENDER_DIR / f"fx-{effect}-{stamp}"
        charge = charging.Charge(
            account_id, provider="fal", ref=charging.attempt_ref(out_stub),
            estimate_usd=usd, key_source=fal.KEY_SOURCE, source=source, dsn=db_path)
        try:
            charge.take()       # an empty balance refuses HERE: nothing submitted
        except ledger.InsufficientCredit as e:
            return {"ok": False, "error": charging.refusal(e, "this effect")}
        try:
            charge.submitted()
            result, skip = fal._submit_and_wait(endpoint, body, http=http,
                                                account_id=account_id)
            url = fal._output_url(result, skip)
            if not url:
                raise RuntimeError("fal effect completed but carried no output URL")
            out_path = out_stub.with_suffix(_suffix(url, row["output"]))
            fal._download(url, out_path)
        except Exception as e:
            charge.release(f"fal effect: {type(e).__name__}")
            raise

        params = {"provider": "fal", "model": effect, "endpoint": endpoint,
                  "effect": effect, "options": options, "source": source,
                  "sources": list(sources or []), "key_source": fal.KEY_SOURCE,
                  **({"project_id": int(project_id)} if project_id else {}),
                  **charge.params()}
        text = prompt or f"{row['label']} {json.dumps(options, sort_keys=True)}"
        try:
            shot_row_id = fal._shot_row_for_prompt(
                text, db_path, "auto-created by effects.run", account_id)
            generation_id = generative.record_generation(
                shot_row_id, LOG_TOOL, text, params=params,
                output_path=str(out_path), cost_usd=usd,
                **kwargs, account_id=account_id)
        except Exception as e:
            charge.release(f"fal effect: unrecorded ({type(e).__name__})")
            raise
        charge.settle(generation_id=generation_id)

        kind = row["output"]
        ctype = ("video/mp4" if kind == "video"
                 else "image/png" if out_path.suffix == ".png" else "image/jpeg")
        media_url = (publish or fal._publish)(out_path, ctype, account_id)
        asset = {"id": None}
        if bank:
            asset = render_assets.record_best_effort(
                account_id=account_id, generation_id=generation_id, tool=LOG_TOOL,
                model=effect, media_kind=kind, prompt=text, media_url=media_url,
                output_path=str(out_path), metadata=params, dsn=db_path)
        return {"ok": True, "media_url": media_url, "generation_id": generation_id,
                "asset_id": asset.get("id"), "path": str(out_path),
                "media_kind": kind, "error": None}
    except Exception as e:
        return {"ok": False, "error": fal._safe_error(e, account_id)}
