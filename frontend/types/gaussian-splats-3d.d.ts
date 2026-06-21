declare module "@mkkellogg/gaussian-splats-3d" {
  export class Viewer {
    constructor(options?: Record<string, unknown>);
    camera: import("three").PerspectiveCamera;
    splatMesh?: import("three").Object3D;
    addSplatScene(path: string, options?: Record<string, unknown>): Promise<void>;
    start(): void;
    dispose(): Promise<void>;
  }
}
