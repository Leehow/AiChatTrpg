declare module "@3d-dice/dice-box" {
  interface DiceBoxConfig {
    assetPath: string;
    theme?: string;
    scale?: number;
    gravity?: number;
    throwForce?: number;
    spinForce?: number;
    startingHeight?: number;
    settleTimeout?: number;
    offscreen?: boolean;
    delay?: number;
    lightIntensity?: number;
    [key: string]: unknown;
  }

  interface DieResult {
    value?: number;
    sides?: number;
    groupId?: number;
    [key: string]: unknown;
  }

  export default class DiceBox {
    constructor(selector: string, config: DiceBoxConfig);
    init(): Promise<void>;
    roll(notation: string): Promise<DieResult[]>;
    add(notation: string): Promise<DieResult[]>;
    clear(): void;
    updateConfig(config: Partial<DiceBoxConfig>): void;
  }
}
