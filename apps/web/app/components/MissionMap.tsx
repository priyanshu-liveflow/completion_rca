"use client";

import { ArrowRight } from "lucide-react";
import { NodeId, ProofNode } from "../lib/types";
import styles from "./MissionControlPage.module.css";

interface MissionMapProps {
  nodes: ProofNode[];
  selectedNode: NodeId | null;
  onSelect: (nodeId: NodeId | null) => void;
}

function nodeClass(node: ProofNode, selected: boolean): string {
  return [
    styles.node,
    styles.mapButton,
    node.status === "amber" && styles.nodeAmber,
    node.status === "red" && styles.nodeRed,
    node.status === "green" && styles.nodeGreen,
    selected && styles.nodeSelected,
  ]
    .filter(Boolean)
    .join(" ");
}

export default function MissionMap({
  nodes,
  selectedNode,
  onSelect,
}: MissionMapProps) {
  const toggle = (id: NodeId) => {
    onSelect(selectedNode === id ? null : id);
  };

  const children: React.ReactNode[] = [];

  nodes.forEach((node, index) => {
    children.push(
      <button
        key={node.id}
        type="button"
        aria-pressed={selectedNode === node.id}
        className={nodeClass(node, selectedNode === node.id)}
        onClick={() => toggle(node.id)}
        onKeyDown={(event) => {
          if (event.key !== "Enter" && event.key !== " ") return;
          event.preventDefault();
          toggle(node.id);
        }}
      >
        <div className={styles.nodeRole}>{node.role}</div>
        <div className={styles.nodeLabel}>{node.label}</div>
        <div className={styles.nodeDetail}>{node.detail}</div>
        {node.status === "static" && (
          <span className={styles.staticBadge}>static analysis</span>
        )}
      </button>
    );

    if (index < nodes.length - 1) {
      children.push(
        <span
          key={`${node.id}-arrow`}
          className={styles.arrow}
          aria-hidden="true"
        >
          <ArrowRight size={16} />
        </span>
      );
    }
  });

  return (
    <section className={styles.map} aria-label="Dependency upgrade proof chain">
      <h2 className={styles.mapTitle}>Dependency upgrade proof chain</h2>
      <div className={styles.chain}>{children}</div>
    </section>
  );
}
