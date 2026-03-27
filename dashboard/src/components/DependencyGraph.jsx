import { useEffect, useRef, useState } from "react";
import ForceGraph2D from "react-force-graph-2d";

export default function DependencyGraph({ graph }) {
  const fgRef = useRef();
  const containerRef = useRef();
  const [size, setSize] = useState({ width: 0, height: 0 });

  // ✅ Track container size (responsive)
  useEffect(() => {
    const resize = () => {
      if (containerRef.current) {
        setSize({
          width: containerRef.current.offsetWidth,
          height: containerRef.current.offsetHeight
        });
      }
    };

    resize(); // initial
    window.addEventListener("resize", resize);
    return () => window.removeEventListener("resize", resize);
  }, []);

  // ✅ Center graph AFTER render
  useEffect(() => {
    if (fgRef.current && size.width && size.height) {
      setTimeout(() => {
        fgRef.current.zoomToFit(400, 100); // duration + padding
      }, 300);
    }
  }, [graph, size]);

  if (!graph || !graph.nodes || !graph.edges) {
    return (
      <div className="h-full flex items-center justify-center text-gray-400">
        Waiting for graph data...
      </div>
    );
  }

  const graphData = {
    nodes: graph.nodes.map((n) => ({
      id: n.id,
      color: n.health === "anomaly" ? "#ef4444" : "#22c55e"
    })),
    links: graph.edges.map((e) => ({
      source: e.source,
      target: e.target
    }))
  };

  return (
    <div ref={containerRef} className="w-full h-full">
      <ForceGraph2D
        ref={fgRef}
        graphData={graphData}
        width={size.width}
        height={size.height}

        // 🧠 BETTER SPACING (VERY IMPORTANT)
        d3AlphaDecay={0.02}
        d3VelocityDecay={0.3}

        // 🔥 SPREAD NODES PROPERLY
        d3Force="charge"
        d3ForceStrength={-300}

        nodeRelSize={10}
        nodeLabel="id"

        nodeCanvasObject={(node, ctx, globalScale) => {
          const label = node.id;
          const fontSize = 14 / globalScale;
          ctx.font = `${fontSize}px Sans-Serif`;

          // 🔥 glow effect
          ctx.shadowBlur = 15;
          ctx.shadowColor = node.color;

          // node
          ctx.beginPath();
          ctx.arc(node.x, node.y, 10, 0, 2 * Math.PI);
          ctx.fillStyle = node.color;
          ctx.fill();

          ctx.shadowBlur = 0;

          // label
          ctx.fillStyle = "#fff";
          ctx.fillText(label, node.x + 12, node.y + 4);
        }}

        linkColor={() => "#94a3b8"}
        linkWidth={2}

        linkDirectionalParticles={3}
        linkDirectionalParticleWidth={2}
      />
    </div>
  );
}