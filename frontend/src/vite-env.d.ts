/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE_URL?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}

declare module '*/EmergencyHelpModal' {
  import { ComponentType } from 'react'
  const EmergencyHelpModal: ComponentType<{
    isOpen: boolean
    onClose: () => void
    stationCode?: string
  }>
  export default EmergencyHelpModal
}

declare module '*/StationBlueprintModal' {
  import { ComponentType } from 'react'
  const StationBlueprintModal: ComponentType<{
    isOpen: boolean
    onClose: () => void
    initialStation?: string
    initialTargetPlatform?: string
    onLaunchAR?: () => void
  }>
  export default StationBlueprintModal
}
