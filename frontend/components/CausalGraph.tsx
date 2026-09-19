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
import type { AssessmentLevel, Hypothesis } from "@/lib/review";
import { AiIcon, CheckIcon } from "./ui";

/** Edge weight and label both encode strength, so it is never colour-only. */
const EDGE_STYLE: Record<AssessmentLevel, { stroke: string; width: number; dash?: string }> = {
  "Strongly supported": { stroke: "#34d399", width: 2.6 },
  "Moderately supported": { stroke: "#3ddbd0", width: 2 },
  "Weakly supported": { stroke: "#fbbf24", width: 1.5, dash: "5 4" },
  "Not supported": { stroke: "#fb7185", width: 1.2, dash: "2 5" },
  "Insufficient evidence": { stroke: "#5b6b88", width: 1.2, dash: "2 5" },
};

const UNASSESSED = { stroke: "#3d4f70", width: 1, dash: "1 6" };

type CauseData = {
  title: string;
  kind: string;
  reviewerAssessment: AssessmentLevel | null;
  aiAssessment: AssessmentLevel | null;
  selected: boolean;
  counts: { s: number; c: number; u: number };
};

function CauseNode({ data }: NodeProps<Node<CauseData>>) {
  return (
    <div
      className={`w-[248px] rounded-xl border px-3.5 py-2.5 text-left shadow-lg transition ${
        data.selected
          ? "border-accent-400 bg-ink-800 ring-2 ring-accent-500/40"
          : "border-ink-600 bg-ink-850 hover:border-ink-500"
      }`}
    >
      <p className="text-[9.5px] font-semibold uppercase tracking-[0.12em] text-slate-muted">
        {data.kind.replace(/_/g, " ").toLowerCase()}
      </p>
      <p className="mt-1 text-[12.5px] font-medium leading-snug text-slate-soft">{data.title}</p>

      <div className="mt-2 flex items-center gap-2.5 font-mono text-[10px]">
        <span className="text-support-400">+{data.counts.s}</span>
        <span className="text-against-400">−{data.counts.c}</span>
        <span className="text-unknown-400">?{data.counts.u}</span>
      </div>

      <div className="mt-1.5 border-t border-ink-700 pt-1.5">
        {data.reviewerAssessment ? (
          <p className="flex items-center gap-1 text-[10px] text-accent-400">
            <CheckIcon className="h-2.5 w-2.5" />
            {data.reviewerAssessment}
          </p>
        ) : (
          <p className="text-[10px] text-slate-muted">awaiting your assessment</p>
        )}
        {data.aiAssessment && data.aiAssessment !== data.reviewerAssessment && (
          <p className="flex items-center gap-1 text-[9.5px] text-violet-300">
            <AiIcon className="h-2.5 w-2.5" />
            AI: {data.aiAssessment}
          </p>
        )}
      </div>

      <Handle type="source" position={Position.Right} className="!border-ink-600 !bg-ink-500" />
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
      <Handle type="target" position={Position.Left} className="!border-ink-600 !bg-ink-500" />
    </div>
  );
}

// Module scope: React Flow warns when nodeTypes is recreated each render.
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
    const gapY = 138;
    const height = Math.max(1, hypotheses.length) * gapY;

    const causeNodes: Node[] = hypotheses.map((h, i) => ({
      id: h.id,
      type: "cause",
      position: { x: 0, y: i * gapY },
      data: {
        title: h.label,
        kind: h.kind,
        reviewerAssessment: h.reviewer_assessment,
        aiAssessment: h.ai_assessment,
        selected: h.id === selectedId,
        counts: {
          s: h.evidence.filter((e) => e.valence === "SUPPORTING").length,
          c: h.evidence.filter((e) => e.valence === "CONTRADICTING").length,
          u: h.evidence.filter((e) => e.valence === "UNKNOWN").length,
        },
      } satisfies CauseData,
    }));

    const eventNode: Node = {
      id: "__event",
      type: "event",
      position: { x: 440, y: height / 2 - gapY / 2 },
      data: { title: adverseEvent },
      selectable: false,
    };

    const causeEdges: Edge[] = hypotheses.map((h) => {
      // The graph reflects the REVIEWER's assessment. An unassessed hypothesis
      // gets a faint placeholder edge rather than borrowing the AI's opinion.
      const level = h.reviewer_assessment;
      const style = level ? EDGE_STYLE[level] : UNASSESSED;
      const isSel = h.id === selectedId;
      return {
        id: `${h.id}->event`,
        source: h.id,
        target: "__event",
        label: level ? level.replace(" supported", "") : "unassessed",
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

  // A fixed height made fitView shrink a long list to illegibility and still
  // clip it. Grow with the node count instead, within sane bounds.
  const height = Math.min(880, Math.max(360, hypotheses.length * 122 + 90));

  return (
    <div className="w-full" style={{ height }}>
      <ReactFlow
        key={hypotheses.length}
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        onNodeClick={(_, node) => {
          if (node.id !== "__event") onSelect(node.id);
        }}
        fitView
        fitViewOptions={{ padding: 0.18 }}
        // Attribution left in place: hiding it requires a React Flow Pro
        // subscription, which this project does not have.
        nodesDraggable={false}
        nodesConnectable={false}
        edgesFocusable={false}
        zoomOnScroll={false}
        panOnScroll
      >
        <Background variant={BackgroundVariant.Dots} gap={22} size={1} color="#1d2942" />
      </ReactFlow>
    </div>
  );
}
