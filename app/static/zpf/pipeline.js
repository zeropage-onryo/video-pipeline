/* Pipeline — the board you decide on, and nothing else.

   Scenes and concepts were the same row all along (a concept IS one
   scene IS one prompt, 2026-08-26); keeping them as two tabs onto one
   table only meant two places to look for the same card. They are
   merged (2026-08-28). The idea is typed on Studio, the spend is
   approved in Queue, and this page holds exactly one question: which of
   these is worth rendering.

   The approve/deny concept loop and the hold queue that used to live
   here went with the merge -- denying a concept is what the Dev
   Studio's grade queue does, against every archived row, with the
   teach-to-RAG shelves behind it. */
import { state } from './shared.js';
import { initBoard, renderBoard } from './scenes.js';

export function initPipeline() {
  initBoard();
}

export async function renderPipeline() {
  document.getElementById('pbrand').textContent = `brand · ${state.brand}`;
  return renderBoard();
}