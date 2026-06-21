"use client";

import { useEffect, useRef, useState } from "react";
import { PerspectiveCamera, Vector3, WebGLRenderer } from "three";

type Props = {
  transitioning: boolean;
  emotionColor: string;
  inputEnergy: number;
};

type NavigatorWithMemory = Navigator & { deviceMemory?: number };

export default function SplatScene({ transitioning, emotionColor, inputEnergy }: Props) {
  const rootRef = useRef<HTMLDivElement>(null);
  const viewerRef = useRef<import("@mkkellogg/gaussian-splats-3d").Viewer | null>(null);
  const [state, setState] = useState<"idle" | "loading" | "ready" | "fallback">("idle");

  useEffect(() => {
    const root = rootRef.current;
    if (!root) return;
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const memory = (navigator as NavigatorWithMemory).deviceMemory;
    const canvas = document.createElement("canvas");
    const hasWebGL = Boolean(canvas.getContext("webgl2") || canvas.getContext("webgl"));
    if (reduced || !hasWebGL || (memory !== undefined && memory <= 2)) {
      setState("fallback");
      return;
    }

    let disposed = false;
    let disposeStarted = false;
    let localViewer: import("@mkkellogg/gaussian-splats-3d").Viewer | null = null;
    let localRenderer: WebGLRenderer | null = null;
    let resizeObserver: ResizeObserver | null = null;
    const disposeRenderer = () => {
      resizeObserver?.disconnect();
      resizeObserver = null;
      if (!localRenderer) return;
      const renderer = localRenderer;
      localRenderer = null;
      renderer.dispose();
      if (renderer.domElement.parentNode === root) root.removeChild(renderer.domElement);
    };
    const disposeViewer = () => {
      if (disposeStarted) return;
      disposeStarted = true;
      if (!localViewer) {
        disposeRenderer();
        return;
      }
      if (viewerRef.current === localViewer) viewerRef.current = null;
      try {
        void localViewer.dispose()
          .catch(() => {
            // Loading can be aborted while the worker is still settling.
          })
          .finally(disposeRenderer);
      } catch {
        disposeRenderer();
      }
    };
    const observer = new IntersectionObserver(async ([entry]) => {
      if (!entry.isIntersecting || viewerRef.current || disposed) return;
      observer.disconnect();
      setState("loading");
      try {
        const GaussianSplats3D = await import("@mkkellogg/gaussian-splats-3d");
        if (disposed) return;
        const width = Math.max(root.clientWidth, 1);
        const height = Math.max(root.clientHeight, 1);
        const renderer = new WebGLRenderer({ antialias: false, alpha: true, powerPreference: "high-performance" });
        renderer.setPixelRatio(Math.min(window.devicePixelRatio, 1.5));
        renderer.setSize(width, height, false);
        renderer.setClearColor(0x000000, 0);
        root.appendChild(renderer.domElement);
        localRenderer = renderer;
        const camera = new PerspectiveCamera(58, width / height, 0.1, 1000);
        camera.position.set(0, 24, -34);
        camera.lookAt(0, 30, 118);
        resizeObserver = new ResizeObserver(() => {
          if (!localRenderer || disposed) return;
          const nextWidth = Math.max(root.clientWidth, 1);
          const nextHeight = Math.max(root.clientHeight, 1);
          camera.aspect = nextWidth / nextHeight;
          camera.updateProjectionMatrix();
          localRenderer.setSize(nextWidth, nextHeight, false);
        });
        resizeObserver.observe(root);
        const viewer = new GaussianSplats3D.Viewer({
          rootElement: root,
          renderer,
          camera,
          cameraUp: [0, -1, 0],
          ignoreDevicePixelRatio: window.devicePixelRatio > 1.5,
          sharedMemoryForWorkers: false,
          gpuAcceleratedSort: false,
          integerBasedSort: false,
          dynamicScene: true,
          useBuiltInControls: true,
        });
        localViewer = viewer;
        viewerRef.current = viewer;
        await viewer.addSplatScene(process.env.NEXT_PUBLIC_SPLAT_URL || "/assets/emotion-field.ply", {
          splatAlphaRemovalThreshold: 8,
          showLoadingUI: false,
          progressiveLoad: true,
          scale: [0.72, 0.72, 0.72],
        });
        if (disposed) {
          disposeViewer();
          return;
        }
        viewer.start();
        setState("ready");
      } catch {
        if (!disposed) setState("fallback");
      }
    }, { rootMargin: "240px" });
    observer.observe(root);
    return () => {
      disposed = true;
      observer.disconnect();
      disposeViewer();
    };
  }, []);

  useEffect(() => {
    const viewer = viewerRef.current;
    if (!viewer || !transitioning) return;
    const start = performance.now();
    const origin = viewer.camera.position.clone();
    const target = new Vector3(0, 31, 184);
    let frame = 0;
    const animate = (now: number) => {
      const progress = Math.min(1, (now - start) / 1080);
      const eased = 1 - Math.pow(1 - progress, 3);
      viewer.camera.position.lerpVectors(origin, target, eased);
      viewer.camera.lookAt(0, 31 + Math.sin(progress * 18) * 2.5, 330);
      if (viewer.splatMesh) {
        viewer.splatMesh.rotation.z = Math.sin(progress * 26) * (1 - progress) * 0.028;
        viewer.splatMesh.rotation.y += 0.002 + progress * 0.006;
      }
      if (progress < 1) frame = requestAnimationFrame(animate);
    };
    frame = requestAnimationFrame(animate);
    return () => cancelAnimationFrame(frame);
  }, [transitioning]);

  return (
    <div
      className={`splatStage ${transitioning ? "isDiving" : ""}`}
      style={{ "--splat-emotion": emotionColor, "--input-energy": inputEnergy } as React.CSSProperties}
    >
      <div className="splatPoster" aria-hidden="true">
        <i /><i /><i /><i />
      </div>
      <div ref={rootRef} className={`splatViewport is-${state}`} aria-label="可拖拽探索的情绪共感场" />
      <div className="splatTint" />
      <div className="turbulenceVeil" />
      <div className="splatHud">
        <span><b />LIVE EMOTION FIELD</span>
        <span>{state === "ready" ? "拖拽以改变观察角度" : state === "loading" ? "正在聚合情绪微粒" : "低功耗共感场"}</span>
      </div>
    </div>
  );
}
