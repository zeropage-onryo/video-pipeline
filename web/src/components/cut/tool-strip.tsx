"use client";

/* The strip between the viewer and the timeline: the bin's tabs on the
   left (they open the left panel -- one bin, reached two ways), the edit
   tools in the middle, snapping and zoom on the right. */
import { ArrowLeftRight, Captions, Diamond, Film, Magnet, MousePointer2, Music, Scissors, Search, Slice, ZoomIn, ZoomOut } from "lucide-react";
import { useCut } from "@/lib/cut/store";
import { addMarkerAtPlayhead, splitAtPlayhead } from "@/lib/cut/actions";
import { ppsToSlider, sliderToPps } from "@/lib/cut/timeline";
import { zoomBy, zoomToFit } from "@/components/cut/commands";

export function ToolStrip() {
  const tool = useCut((s) => s.tool);
  const setTool = useCut((s) => s.setTool);
  const snapOn = useCut((s) => s.snapOn);
  const toggleSnap = useCut((s) => s.toggleSnap);
  const pps = useCut((s) => s.pps);
  const setPps = useCut((s) => s.setPps);
  const leftTab = useCut((s) => s.leftTab);
  const setLeftTab = useCut((s) => s.setLeftTab);
  return (
    <div className="cx-tools">
      <button type="button" className="cx-btn" aria-pressed={leftTab === "media"} onClick={() => setLeftTab("media")} title="Media bin">
        <Film /> Media
      </button>
      <button type="button" className="cx-btn" aria-pressed={leftTab === "text"} onClick={() => setLeftTab("text")} title="Text & captions (T)">
        <Captions /> Text
      </button>
      <button type="button" className="cx-btn" aria-pressed={leftTab === "audio"} onClick={() => setLeftTab("audio")} title="Audio">
        <Music /> Audio
      </button>
      <button type="button" className="cx-btn" aria-pressed={leftTab === "search"} onClick={() => setLeftTab("search")} title="Search the footage">
        <Search /> Search
      </button>
      <span className="cx-sep" style={{ margin: "0 6px" }} />
      <button type="button" className="cx-btn" aria-pressed={tool === "select"} onClick={() => setTool("select")} title="Select (A)">
        <MousePointer2 />
      </button>
      <button type="button" className="cx-btn" aria-pressed={tool === "blade"} onClick={() => setTool("blade")} title="Blade (C) — click a clip to cut it">
        <Slice />
      </button>
      <button type="button" className="cx-btn" onClick={splitAtPlayhead} title="Split at playhead (B)">
        <Scissors />
      </button>
      <button type="button" className="cx-btn" onClick={() => addMarkerAtPlayhead()} title="Add marker (M)">
        <Diamond />
      </button>
      <span className="spacer" />
      <button
        type="button"
        className={`cx-btn${snapOn ? " on" : ""}`}
        aria-pressed={snapOn}
        onClick={toggleSnap}
        title={`Snapping ${snapOn ? "on" : "off"} (N)`}
      >
        <Magnet /> <span className="cx-label" style={{ color: "inherit" }}>snap</span>
      </button>
      <span className="cx-sep" style={{ margin: "0 6px" }} />
      <span className="cx-zoom">
        <button type="button" className="cx-btn" onClick={() => zoomBy(1 / 1.5)} title="Zoom out (−)">
          <ZoomOut />
        </button>
        <input
          type="range"
          min={0}
          max={1000}
          value={Math.round(ppsToSlider(pps) * 1000)}
          onChange={(e) => setPps(sliderToPps(Number(e.target.value) / 1000))}
          aria-label="Zoom"
        />
        <button type="button" className="cx-btn" onClick={() => zoomBy(1.5)} title="Zoom in (+)">
          <ZoomIn />
        </button>
        <button type="button" className="cx-btn" onClick={zoomToFit} title="Zoom to fit (⇧Z)">
          <ArrowLeftRight />
        </button>
      </span>
    </div>
  );
}
