import * as PIXI from 'pixi.js'
import { ShaderSystem } from '@pixi/core'
import { install as installCspSupport } from '@pixi/unsafe-eval'
import type { Live2DModel as Live2DModelType } from 'pixi-live2d-display/cubism4'

declare global {
  interface Window {
    Live2DCubismCore?: unknown
  }
}

const MODEL_PATH = new URL(
  `${import.meta.env.BASE_URL}live2d/mao/mao_pro.model3.json`,
  window.location.href
).toString()
const CORE_PATH = new URL(
  `${import.meta.env.BASE_URL}live2d/mao/live2dcubismcore.min.js`,
  window.location.href
).toString()
const LIP_SYNC_PARAMETER_ID = 'ParamA'
const EXAMPLE_MOTION_GROUP = ''

type ParameterModel = {
  getParameterIndex(parameterId: string): number
  getParameterDefaultValue(parameterIndex: number): number
  getParameterMaximumValue(parameterIndex: number): number
  setParameterValueByIndex(parameterIndex: number, value: number, weight?: number): void
}

export class Live2DController {
  private app: PIXI.Application | null = null
  private model: InstanceType<typeof Live2DModelType> | null = null
  private live2DModelClass: typeof Live2DModelType | null = null
  private speaking = false

  async mount(canvas: HTMLCanvasElement): Promise<void> {
    if (this.app) return
    await loadCubismCore()
    const { Live2DModel } = await import('pixi-live2d-display/cubism4')
    installCspSupport({ ShaderSystem })
    this.live2DModelClass = Live2DModel
    Live2DModel.registerTicker(PIXI.Ticker)

    this.app = new PIXI.Application({
      view: canvas,
      backgroundAlpha: 0,
      antialias: true,
      autoStart: true,
      resizeTo: canvas.parentElement ?? undefined
    })
    await this.load()
  }

  async load(): Promise<void> {
    if (!this.app) throw new Error('Live2D 画布尚未初始化')
    if (this.model) {
      this.model.internalModel.off('beforeModelUpdate', this.updateMouth)
      this.app.stage.removeChild(this.model)
      this.model.destroy({ children: true, texture: false, baseTexture: false })
      this.model = null
    }

    if (!this.live2DModelClass) throw new Error('Cubism 4 运行时尚未加载')
    const model = await this.live2DModelClass.from(MODEL_PATH, {
      autoInteract: true
    })
    model.anchor.set(0.5, 1)
    this.model = model
    model.internalModel.on('beforeModelUpdate', this.updateMouth)
    this.app.stage.addChild(model)
    this.fit()
    await model.motion('Idle')
    window.addEventListener('resize', this.fit, { passive: true })
  }

  setSpeaking(speaking: boolean): void {
    this.speaking = speaking
    this.updateMouth()
  }

  async playExampleMotion(): Promise<boolean> {
    return this.model?.motion(EXAMPLE_MOTION_GROUP, 0) ?? false
  }

  async setExpression(expressionId: string): Promise<boolean> {
    return this.model?.expression(expressionId) ?? false
  }

  destroy(): void {
    if (this.model) {
      this.model.internalModel.off('beforeModelUpdate', this.updateMouth)
      this.model.destroy({ children: true, texture: false, baseTexture: false })
    }
    this.app?.destroy(false, { children: true, texture: false, baseTexture: false })
    window.removeEventListener('resize', this.fit)
    this.model = null
    this.live2DModelClass = null
    this.app = null
  }

  private readonly updateMouth = (): void => {
    const core = this.model?.internalModel?.coreModel as ParameterModel | undefined
    if (!core) return

    const index = core.getParameterIndex(LIP_SYNC_PARAMETER_ID)
    if (index < 0) return

    const value = this.speaking
      ? core.getParameterMaximumValue(index)
      : core.getParameterDefaultValue(index)
    core.setParameterValueByIndex(index, value, 1)
  }

  private readonly fit = (): void => {
    if (!this.model || !this.app?.view) return
    const canvas = this.app.view as HTMLCanvasElement
    const scale = Math.min(canvas.clientWidth / this.model.width, canvas.clientHeight / this.model.height) * 0.9
    this.model.scale.set(scale)
    this.model.x = canvas.clientWidth / 2
    this.model.y = canvas.clientHeight * 0.98
  }
}

let cubismCorePromise: Promise<void> | null = null

function loadCubismCore(): Promise<void> {
  if (window.Live2DCubismCore) return Promise.resolve()
  if (cubismCorePromise) return cubismCorePromise

  cubismCorePromise = new Promise((resolve, reject) => {
    const script = document.createElement('script')
    script.src = CORE_PATH
    script.onload = () => resolve()
    script.onerror = () => reject(new Error('Cubism 4 核心运行时加载失败'))
    document.head.appendChild(script)
  })

  return cubismCorePromise
}
