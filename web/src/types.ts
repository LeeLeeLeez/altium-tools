/** 后端返回的数据结构（与 Python 端 api/*.py 一一对应）。 */

export interface PageProps {
  /** 往底部状态栏写一行（普通消息）。 */
  setStatus: (msg: string) => void
  /** 往底部状态栏写一行（错误，会把状态点变红）。 */
  setStatusError: (msg: string) => void
  /** 当前页是否可见 —— 页面在不可见时刷新数据。 */
  active: boolean
}

/* ------------------------------------------------------------------ 通用 */
export interface Config {
  [key: string]: string | number | boolean | string[] | undefined
}

/* ------------------------------------------------------------ 画中点短线 */
export interface MidpointSpec {
  orient: 'v' | 'h'
  tab: string
  title: string
  hint: string
  require: string
  startLabel: string
  button: string
  word: string
  keys: string[]
  legacy: string[]
  defaults: string[]
}

export interface MidpointMeta {
  presets: { label: string; value: number }[]
  layers: string[]
  specs: { v: MidpointSpec; h: MidpointSpec }
}

export interface TrackInfo {
  layer: string
  x1: number
  y1: number
  x2: number
  y2: number
  width: number
  objectId: string
  vertical: boolean
  horizontal: boolean
  row: string
}

/* ---------------------------------------------------------------- 叠层 */
export interface StackupRow {
  i: number
  name: string
  type: string
  typeLabel: string
  oz: number
  ozText: string
  gap: number | null
}

export interface StackupResult {
  total: number
  cu: number
  diel: number
  simTotal: number
  cuSim?: number
  dielSim?: number
  mode: string
  ATp: number
  ATs: number
  iface: number
  errors: string[]
  counts: Record<string, number>
  mmf: { peak: number; integral: number; sym: number }
  labels: string[]
  names: string[]
  text: string
}

export interface MmfSeries {
  state: number
  mmfAfter: number[]
  peak?: number
  integral?: number
  net?: number
}

export interface StripItem {
  index: number
  type: string
  label: string
  color: string
}

export interface StackupState {
  ok: boolean
  params: Record<string, string>
  rect: string
  cumode: string
  seq: string[]
  names: string[]
  rows: StackupRow[]
  result: StackupResult | null
  mmfSeries: MmfSeries[]
  strip: StripItem[]
  confirmed: { names: string[] | null; seq: string[] | null; label: string }
  template: { srcFile: string | null; label: string; copper: number; dielectric: number }
  cuMode: { globalEditable: boolean; perLayerEditable: boolean }
  typeLabels: { value: string; label: string }[]
  cuChoices: string[]
  error: string | null
}

/* ------------------------------------------------------------ 层交换等 */
export interface CopperLayer {
  name: string
  order?: number
  copper_thickness_mils?: number
}

export interface PcbStackup {
  board: string
  copper: CopperLayer[]
  all: CopperLayer[]
}

export interface GeneratedScript {
  ok: boolean
  pasPath: string
  prjPath: string
  stem: string
  candidates?: number
  bytes: number
  procedure: string
  reportFile: string
  log: string[]
  repour?: boolean
  repourMode?: string
  copyMode?: string
  symA?: string
  symB?: string
}

/* ------------------------------------------------------------ 工程快照 */
export interface SnapshotInfo {
  date: string
  hhmm: string
  path: string
  rel: string
  mtime: number
  mtimeText: string
}

export interface SnapshotScan {
  ok: boolean
  root: string
  snaps: SnapshotInfo[]
  source: SnapshotInfo | null
  note: string | null
  dates: { date: string; snaps: SnapshotInfo[] }[]
  counts: { dates: number; snaps: number }
}

export interface SnapshotPlan {
  root: string
  src: string
  ts: string
  today: string
  todayDir: string
  dst: string
  keepProj: string | null
  pcbNote: string | null
  files: { rel: string; abs: string; size: number }[]
  skippedDirs: { rel: string; nfiles: number; nbytes: number }[]
  skippedFiles: { rel: string; size: number }[]
  renames: { from: string; to: string }[]
  totalBytes: number
  skippedBytes: number
  human: string
  prjpcb: string | null
}
