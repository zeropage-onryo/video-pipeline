---
name: product-still
title: Product still
for: draw a still of a real product from its own photos -- a packshot, a hero frame, or in use
output: image
order: 40
---
# Product still

A still of a real, named product. The product in the picture has to BE the product: its shape, label, colours and proportions come from its real photos, never from a description of it.

## Get the product first

- Photos are attached, or the product is an @Element: use them. They ride along with the still, so you do not describe the label again.
- No photos yet: offer to find them. Call find_references with the product named exactly as a shopper would type it ("Ghost energy drink orange cream can") and departments ["prop"]. A clean packshot on white is the best reference there is. Or they paste the product's page link, and the studio reads its pictures.
- Never draw a named product from its name alone. The label will be invented.

## Pick the kind of still

Offer these as choices when they have not said:

- Packshot. The product alone, straight-on or three-quarter, on a seamless background, soft even light, true colour. For a listing, and as a clean reference for later shots.
- Hero. The product as the subject of a designed frame: one surface, one light with a direction, one supporting element (condensation, a shadow, an ingredient). For an ad or a poster.
- In use. A hand or a person with it, in a real place, the product still readable. For social and lifestyle.

## Write the prompt

It is handed to the image model as you write it. Write it as a photographer's brief, in this order:

1. The lock: "the exact product from the reference photos -- same shape, label, colours and proportions", with its name in the person's own words.
2. Placement and angle: where it sits in the frame, which face is to camera, how much of the frame it fills.
3. Surface and setting: one or two concrete materials -- a wet steel counter, raw linen, poured concrete.
4. Light: one main source, its direction and its quality (hard window light from the left, soft overhead), and what it does on the product (a rim along the shoulder, a sharp shadow).
5. Lens and distance: macro, normal or short telephoto, and how deep the focus is.
6. Finish: true materials and reflections, real condensation or dust where it suits, no added text, no extra logos, nothing that changes the label.

It is a still: no camera moves, and no "then". Never "cinematic", "epic" or "8K".

## Shape

Give an aspect only when they asked for one or the use decides it: 1:1 or 4:5 for a feed, 9:16 for a story, 16:9 for a banner.

## Hand it over

Call make_image with the prompt, and the aspect when one is set -- only when they asked for the still. It waits for their Approve beside its price.

## After it lands

Offer one round of fixes, as choices:

- the label is unreadable or wrong: a clearer reference photo. When the result says the references were not used, the image model picked in the composer takes none -- tell them to switch model there and draw again;
- too glossy: name a real light and a real surface.

Then offer the next kind of still from the list, or to turn the keeper into a shot.
