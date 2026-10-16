// Artwork for the AI Voice Agent page (supplied by the team). The robot, mic button and voice wave
// were delivered on a white background; the border-connected white was cut to transparency so they
// can sit directly on the station photo. Every image keeps its original pixel size and aspect ratio.
import micButtonPng from '../assets/voice/mic-button.png'
import micButtonWebp from '../assets/voice/mic-button.webp'
import robotPng from '../assets/voice/robot.png'
import robotWebp from '../assets/voice/robot.webp'
import stationBgJpg from '../assets/voice/station-bg.jpg'
import stationBgWebp from '../assets/voice/station-bg.webp'
import voiceWavePng from '../assets/voice/voice-wave.png'
import voiceWaveWebp from '../assets/voice/voice-wave.webp'

export interface Art { png: string; webp: string; width: number; height: number }

export const VOICE_ART = {
  background: { png: stationBgJpg, webp: stationBgWebp, width: 831, height: 396 },
  robot: { png: robotPng, webp: robotWebp, width: 370, height: 402 },
  micButton: { png: micButtonPng, webp: micButtonWebp, width: 327, height: 383 },
  voiceWave: { png: voiceWavePng, webp: voiceWaveWebp, width: 518, height: 102 },
} as const satisfies Record<string, Art>
