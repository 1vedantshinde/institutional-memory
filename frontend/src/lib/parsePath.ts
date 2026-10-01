/**
 * Safely parse condition ID and recording number from a source_path like
 *   .../N_4/Recording 12.csv
 *   dataset/Readngs_DAQ_Data/4_S800_F35_D0.25/Recording 1.csv   (real layout; see
 *     recording_folder_pattern in config/domain.yaml)
 * Returns null fields when the pattern doesn't match.
 */
export interface ParsedPath {
  conditionId: string | null
  recordingNumber: string | null
  basename: string
  fullPath: string
}

export function parsePath(sourcePath: string): ParsedPath {
  const basename = sourcePath.split('/').pop() ?? sourcePath
  const folder = sourcePath.split('/').slice(-2, -1)[0] ?? ''
  const conditionMatch = folder.match(/^(\d+)_S/) ?? sourcePath.match(/N_(\d+)/i)
  const recordingMatch = basename.match(/Recording\s+(\d+)/i)
  return {
    conditionId: conditionMatch ? conditionMatch[1] : null,
    recordingNumber: recordingMatch ? recordingMatch[1] : null,
    basename,
    fullPath: sourcePath,
  }
}
