---
name: character-sheet
title: Character sheet
for: save a person as a character and draw their reference sheet from real photos of them
output: image
order: 10
---
# Character sheet

A character sheet is how the studio holds one person's face and clothes steady from shot to shot. It is drawn from REAL photos of that person and saved with them as a character in Elements. Scenes then name the character with @, and are held to the photos first and the sheet second.

## Before you draw

Look at the photos attached to this turn -- you can see them. Check these, and say plainly what is missing:

- ONE person, the same one in every photo. Two people in frame: ask which one.
- The face is clear in at least one photo: front-on, eyes visible, no sunglasses, not a small figure in a wide shot.
- Coverage. Best is three or more: a front face, a three-quarter or profile, and one full body. With only a face, the sheet has to guess the body and the clothes -- say so before drawing, never after.
- Even light beats a dramatic one. A heavy colour cast or a filter is copied into every panel.

No photos attached: ask for a few of the same person and stop there. Never draw a sheet of a person from a description or from the web, and never hunt a face with find_references.

## What to settle

Ask at most two things, as choices:

- The name the character is saved under. It is theirs to give; when it is the person themself and you do not know their name, ask.
- Clothes: keep what the photos show (the default), or a set outfit they describe. Put ONLY an outfit they stated into `notes`, in a few concrete words -- garment, colour, material. Never invent one.

## Drawing it

Call make_element_sheet with the name and the notes. Never make_image for this. The studio draws one wide image, five panels in a row -- full-body front, three-quarter, side profile, back, head-and-shoulders close-up -- on a plain light-grey background, the same face, hair and clothes in every panel, no text. The call ends your turn; the person approves it beside its price.

## After it lands

Say in one line how to use it: type @ and the name in any scene. Then offer ONE round of fixes, as choices:

- the face drifted: add a clearer front photo to the character, then redraw;
- the clothes are wrong: redraw with the outfit stated;
- feet cropped or a panel missing: redraw.

A redraw is the "Redraw sheet" button on the character's card on the Elements page. Point there; do not save a second character to get a second sheet.

## Not this skill

- A product, a vehicle or an object is a prop Element with its own turnaround sheet, made on the Elements page (New element) from its photos. When they have no photos of it, offer to find them: find_references with the product named exactly and departments ["prop"].
- A place is a location Element, made on the same page.
- An invented person with no photos: the studio does not cast generated faces as characters. Say so, and offer to write the person into the scene as a plain description instead.
