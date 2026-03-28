import { useEffect, useRef } from "react";
import * as d3 from "d3";

const NODE_RADIUS = 18;
const NODE_COLORS = {
  healthy:  "#10b981",
  degraded: "#f59e0b",
  anomaly:  "#ef4444",
};
const EDGE_COLOR_NORMAL   = "#475569";
const EDGE_COLOR_DEGRADED = "#f59e0b";

function edgeWidth(weight) {
  return 1 + (weight ?? 0.5) * 3; // 1–4px
}

export default function DependencyGraph({ streamData }) {
  const containerRef = useRef(null);
  const svgRef       = useRef(null);
  const simRef       = useRef(null);
  const gLinksRef    = useRef(null);
  const gNodesRef    = useRef(null);

  // ── Build/update the graph whenever streamData changes ──────────────
  useEffect(() => {
    const container = containerRef.current;
    const svg       = d3.select(svgRef.current);
    if (!container || !svg) return;

    const graph = streamData?.dependency_graph;
    if (!graph?.nodes?.length) return;

    const W = container.clientWidth  || 360;
    const H = container.clientHeight || 260;

    svg.attr("width", W).attr("height", H).attr("viewBox", `0 0 ${W} ${H}`);

    // ── Identify anomalous nodes ─────────────────────────────────────
    const anomalousIds = new Set(
      graph.nodes.filter((n) => n.health === "anomaly").map((n) => n.id)
    );

    // ── Clone data so D3 can mutate x/y ──────────────────────────────
    const nodesData = graph.nodes.map((n) => ({ ...n }));
    const linksData = graph.edges.map((e) => ({ ...e }));

    // ── LINKS (enter/update/exit) ─────────────────────────────────────
    const gLinks = gLinksRef.current;
    const lSel = gLinks
      .selectAll("line")
      .data(linksData, (d) => `${d.source?.id ?? d.source}→${d.target?.id ?? d.target}`);

    const lEnter = lSel.enter().append("line");
    const lines  = lEnter.merge(lSel);

    lines
      .attr("stroke-width", (d) => edgeWidth(d.weight))
      .attr("stroke", (d) => {
        const s = typeof d.source === "object" ? d.source.id : d.source;
        const t = typeof d.target === "object" ? d.target.id : d.target;
        return anomalousIds.has(s) || anomalousIds.has(t)
          ? EDGE_COLOR_DEGRADED
          : EDGE_COLOR_NORMAL;
      })
      .attr("stroke-dasharray", (d) => {
        const s = typeof d.source === "object" ? d.source.id : d.source;
        const t = typeof d.target === "object" ? d.target.id : d.target;
        return anomalousIds.has(s) || anomalousIds.has(t) ? "6 3" : "none";
      })
      .attr("stroke-opacity", 0.8);

    lSel.exit().remove();

    // ── NODES (enter/update/exit) ─────────────────────────────────────
    const gNodes  = gNodesRef.current;
    const nSel    = gNodes.selectAll("g.node").data(nodesData, (d) => d.id);
    const nEnter  = nSel.enter().append("g").attr("class", "node");

    nEnter.append("circle").attr("r", NODE_RADIUS);
    nEnter.append("text")
      .attr("text-anchor", "middle")
      .attr("dy", NODE_RADIUS + 12)
      .attr("font-size", 9)
      .attr("font-family", "ui-monospace, monospace")
      .attr("fill", "#94a3b8");

    nSel.exit().remove();

    const nodes = nEnter.merge(nSel);

    nodes.select("circle")
      .transition().duration(600)
      .attr("r", NODE_RADIUS)
      .attr("fill", (d) => NODE_COLORS[d.health] || NODE_COLORS.healthy)
      .attr("stroke", (d) => d.health === "anomaly" ? "#ef4444" : "transparent")
      .attr("stroke-width", 3)
      .attr("filter", (d) => d.health === "anomaly" ? "url(#glow-red)" : "none");

    nodes.select("text")
      .text((d) => {
        // Shorten labels so they fit
        return d.id
          .replace("-service", "")
          .replace("api-gateway", "gateway");
      });

    // ── SIMULATION ────────────────────────────────────────────────────
    if (simRef.current) simRef.current.stop();

    const sim = d3
      .forceSimulation(nodesData)
      .force("link",    d3.forceLink(linksData).id((d) => d.id).distance(75).strength(0.7))
      .force("charge",  d3.forceManyBody().strength(-220))
      .force("center",  d3.forceCenter(W / 2, H / 2))
      .force("collide", d3.forceCollide(NODE_RADIUS + 18))
      .alphaDecay(0.035);

    simRef.current = sim;

    sim.on("tick", () => {
      lines
        .attr("x1", (d) => (d.source?.x ?? 0))
        .attr("y1", (d) => (d.source?.y ?? 0))
        .attr("x2", (d) => (d.target?.x ?? 0))
        .attr("y2", (d) => (d.target?.y ?? 0));

      nodes.attr("transform", (d) => `translate(${d.x ?? 0},${d.y ?? 0})`);
    });

    return () => sim.stop();
  }, [streamData]);

  // ── Resize observer: re-set SVG size when container resizes ─────────
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    const ro = new ResizeObserver(() => {
      const W = container.clientWidth;
      const H = container.clientHeight;
      if (W && H && svgRef.current) {
        d3.select(svgRef.current)
          .attr("width", W)
          .attr("height", H)
          .attr("viewBox", `0 0 ${W} ${H}`);
        if (simRef.current) {
          simRef.current.force("center", d3.forceCenter(W / 2, H / 2));
          simRef.current.alpha(0.3).restart();
        }
      }
    });
    ro.observe(container);
    return () => ro.disconnect();
  }, []);

  return (
    <div ref={containerRef} className="w-full h-full relative overflow-hidden">
      <svg ref={svgRef} className="w-full h-full">
        <defs>
          <filter id="glow-red" x="-60%" y="-60%" width="220%" height="220%">
            <feGaussianBlur stdDeviation="5" result="coloredBlur" />
            <feMerge>
              <feMergeNode in="coloredBlur" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
        </defs>
        {/* Attach refs to <g> elements so enter/update/exit stays stable */}
        <g ref={(el) => { gLinksRef.current = d3.select(el); }} />
        <g ref={(el) => { gNodesRef.current = d3.select(el); }} />
      </svg>

      {!streamData?.dependency_graph && (
        <div className="absolute inset-0 flex items-center justify-center text-slate-600 text-xs">
          Waiting for graph data…
        </div>
      )}
    </div>
  );
}