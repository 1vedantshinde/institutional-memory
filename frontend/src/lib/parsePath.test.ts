import { describe, it, expect } from 'vitest'
import { parsePath } from './parsePath'

describe('parsePath', () => {
  it('parses the real dataset layout (<id>_S<S>_F<F>_D<D>/Recording n.csv)', () => {
    const p = parsePath('/home/u/institutional-memory/dataset/Readngs_DAQ_Data/4_S800_F35_D0.25/Recording 1.csv')
    expect(p).toMatchObject({ conditionId: '4', recordingNumber: '1', basename: 'Recording 1.csv' })
  })

  it('does not mistake S/F/D digits for the condition', () => {
    expect(parsePath('data/12_S1000_F4_D0.5/Recording 3.csv').conditionId).toBe('12')
  })

  it('still parses the N_<id> layout', () => {
    expect(parsePath('.../N_4/Recording 12.csv')).toMatchObject({ conditionId: '4', recordingNumber: '12' })
  })

  it('returns null rather than guessing for unknown layouts', () => {
    expect(parsePath('some/other/file.csv')).toMatchObject({ conditionId: null, recordingNumber: null })
  })
})
