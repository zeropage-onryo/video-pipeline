/**
 * What the backend would say, so the UI can be built and reviewed before
 * it is wired up.
 *
 * These are transcriptions of real responses, not invention: the brains
 * rows are what src/gemini_utils.py brain_options() returns, the
 * capability keys are app/api.py compute_capabilities()' own. Keeping
 * them honest is the whole point -- a fixture that drifts from the route
 * builds a screen for a backend that does not exist.
 */
import type { Brain, Capabilities, Job, JobStarted, Me, RatioChoice } from './api'

const brains: { brains: Brain[]; default: string } = {
  brains: [
    {
      id: 'fast',
      label: 'Fast',
      note: 'gemini 3 flash — the default, and what the night runs on',
      default: true,
    },
    {
      id: 'reasoning',
      label: 'Reasoning',
      note: 'gemini 3.1 pro, thinking HIGH — slower, ~4x the tokens, no fallback',
      default: false,
    },
  ],
  default: 'fast',
}

const capabilities: Capabilities = {
  'pipeline.run': true,
  creative_guide: true,
  'pipeline.concepts': true,
  scout: true,
  retrieve: true,
  'assets.list': true,
  'assets.create': true,
  workflows: true,
  jobs: true,
  holds: true,
  analytics: true,
  'runway.generate': true,
  'runway.spend': true,
  'nano.generate': true,
  dev_tools: true,
  manual_lane: false,
}

const jobStarted: JobStarted = { job_id: 'fixture-job', image_refs: 0, brain: 'fast' }
const job: Job = { id: 'fixture-job', status: 'done', detail: '1 concept(s)', ref_id: 412 }

const me: Me = {
  email: 'mike@zeropagefilms.com',
  display_name: 'Michael',
  avatar_url: null,
  account: { slug: 'zeropage', display_name: 'Zero Page', role: 'owner' },
  accounts: [
    { slug: 'zeropage', display_name: 'Zero Page', role: 'owner' },
    { slug: 'antihero', display_name: 'Antihero', role: 'owner' },
  ],
}

const renderChoices: { ratios: RatioChoice[]; default: string } = {
  ratios: [
    { id: '720:1280', label: '9:16', size: '720:1280' },
    { id: '1280:720', label: '16:9', size: '1280:720' },
    { id: '960:960', label: '1:1', size: '960:960' },
    { id: '1104:832', label: '69:52', size: '1104:832' },
  ],
  default: '720:1280',
}

export const FIXTURES = {
  me,
  renderChoices,
  brains,
  capabilities,
  sceneLengths: { choices: [8, 12, 16, 24, 32], default: 8 },
  jobStarted,
  job,
}
