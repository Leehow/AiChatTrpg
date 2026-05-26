export interface TrpgHudCurrentTime {
  day?: number | string | null;
  date?: string | null;
  clock?: string | null;
  period?: string | null;
}

export interface TrpgSceneHudSnapshot {
  currentTime?: TrpgHudCurrentTime | null;
  sceneKey?: string | null;
  sceneName?: string | null;
}
