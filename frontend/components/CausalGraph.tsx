"use client";

import { useMemo } from "react";
import {
  Background,
  BackgroundVariant,
  Handle,
  Position,
  ReactFlow,
  type Edge,
  type Node,
  type NodeProps,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import type { Hypothesis, HypothesisKind, SupportLabel } from "@/lib/types";
import { Panel } from "./ui";

const KIND_LABEL: Record<HypothesisKind, string> = {
  SUSPECT_DRUG: "Suspected drug",
  CONCOMITANT_DRUG: "Concomitant drug",
  INFECTION: "Infection",
  UNDERLYING_DISEASE: "Underlying disease",
  INTERACTION: "Drug interaction",
  INSUFFICIENT_EVIDENCE: "Insufficient evidence",
};

/** Edge weight encodes strength; the edge is also labelled, so not colour-only. */
const EDGE_STYLE: Record<SupportLabel, { stroke: string; width: number; dash?: string }> = {
  "Strong support": { stroke: "#34d399", width: 2.6 },
  "Moderate support": { stroke: "#3ddbd0", width: 2 },
  "Limited support": { stroke: "#fbbf24", width: 1.5, dash: "5 4" },
  "Insufficient evidence": { stroke: "#5b6b88", width: 1.2, dash: "2 5" },
};

type CauseData = {
  title: string;
  kind: HypothesisKind;
  label: SupportLabel;
  selected: boolean;
  counts: { s: number; c: number; u: number };
};

function CauseNode({ data }: NodeProps<Node<CauseData>>) {
  return (
    <div
      className={`w-[230px] rounded-xl border px-3.5 py-2.5 text-left shadow-lg transition ${
        data.selected
          ? "border-accent-400 bg-ink-800 ring-2 ring-accent-500/40"
          : "border-ink-600 bg-ink-850 hover:border-ink-500"
      }`}
    >
      <p className="text-[9.5px] font-semibold uppercase tracking-[0.12em] text-slate-muted">
        {KIND_LABEL[data.kind]}
      </p>
      <p className="mt-1 text-[12.5px] font-medium leading-snug text-slate-soft">{data.title}</p>
      <div className="mt-2 flex items-center gap-2.5 font-mono text-[10px]">
        <span className="text-support-400">+{data.counts.s}</span>
        <span className="text-against-400">−{data.counts.c}</span>
        <span className="text-unknown-400">?{data.counts.u}</span>
        <span className="ml-auto text-[9px] uppercase tracking-wide text-slate-muted">
          {data.label.replace(" support", "")}
        </span>
      </div>
      <Handle type="source" position={Position.Right} className="!bg-ink-500 !border-ink-600" />
    </div>
  );
}

function EventNode({ data }: NodeProps<Node<{ title: string }>>) {
  return (
    <div className="w-[200px] rounded-xl border-2 border-against-400/60 bg-against-bg px-4 py-3 text-center shadow-xl">
      <p className="text-[9.5px] font-semibold uppercase tracking-[0.12em] text-against-400">
        Adverse event
      </p>
      <p className="mt-1 text-sm font-semibold leading-snug text-slate-soft">{data.title}</p>
      <Handle type="target" position={Position.Left} className="!bg-ink-500 !border-ink-600" />
    </div>
  );
}

// Defined once at module scope: React Flow warns if nodeTypes is a new object
// on every render.
const nodeTypes = { cause: CauseNode, event: EventNode };

export default function CausalGraph({
  hypotheses,
  adverseEvent,
  selectedId,
  onSelect,
}: {
  hypotheses: Hypothesis[];
  adverseEvent: string;
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  const { nodes, edges } = useMemo(() => {
    const gapY = 118;
    const height = Math.max(1, hypotheses.length) * gapY;

    const causeNodes: Node[] = hypotheses.map((h, i) => ({
      id: h.id,
      type: "cause",
      position: { x: 0, y: i * gapY },
      data: {
        title: h.hypothesis,
        kind: h.kind,
        label: h.support_label,
        selected: h.id === selectedId,
        counts: {
          s: h.supporting_evidence.length,
          c: h.contradicting_evidence.length,
          u: h.unknown_evidence.length,
        },
      } satisfies CauseData,
    }));

    const eventNode: Node = {
      id: "__event",
      type: "event",
      position: { x: 420, y: height / 2 - gapY / 2 },
      data: { title: adverseEvent },
      selectable: false,
    };

    const causeEdges: Edge[] = hypotheses.map((h) => {
      const style = EDGE_STYLE[h.support_label];
      const isSel = h.id === selectedId;
      return {
        id: `${h.id}->event`,
        source: h.id,
        target: "__event",
        label: h.support_label.replace(" support", ""),
        labelShowBg: false,
        labelStyle: {
          fill: isSel ? "#3ddbd0" : "#7d8ca8",
          fontSize: 9.5,
          fontWeight: 600,
          textTransform: "uppercase",
        },
        style: {
          stroke: isSel ? "#3ddbd0" : style.stroke,
          strokeWidth: isSel ? style.width + 1 : style.width,
          strokeDasharray: style.dash,
          opacity: selectedId && !isSel ? 0.35 : 1,
        },
      };
    });

    return { nodes: [...causeNodes, eventNode], edges: causeEdges };
  }, [hypotheses, adverseEvent, selectedId]);

  return (
    <Panel
      title="Competing causal hypotheses"
      subtitle="Every candidate cause the narrative supports, not a single verdict. Click a node to inspect its evidence."
      bodyClassName="p-0"
    >
      <div className="h-[420px] w-full rounded-b-xl">
        <ReactFlow
          nodes={nodes}
          edges={edges}
          nodeTypes={nodeTypes}
          onNodeClick={(_, node) => {
            if (node.id !== "__event") onSelect(node.id);
          }}
          fitView
          fitViewOptions={{ padding: 0.18 }}
          proOptions={{ hideAttribution: true }}
          nodesDraggable={false}
          nodesConnectable={false}
          edgesFocusable={false}
          zoomOnScroll={false}
          panOnScroll
        >
          <Background variant={BackgroundVariant.Dots} gap={22} size={1} color="#1d2942" />
        </ReactFlow>
      </div>
      <div className="flex flex-wrap items-center gap-x-5 gap-y-1.5 border-t border-ink-700/60 px-5 py-3 font-mono text-[10px] text-slate-muted">
        <span>
          <span className="text-support-400">+n</span> supporting
        </span>
        <span>
          <span className="text-against-400">−n</span> contradicting
        </span>
        <span>
          <span className="text-unknown-400">?n</span> not reported
        </span>
        <span className="ml-auto font-sans">Edge weight and label both encode strength.</span>
      </div>
    </Panel>
  );
}
