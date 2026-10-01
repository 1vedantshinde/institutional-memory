// MSW server for Node (Vitest / test) environment.
// Import this in vitest setup and call server.listen() / server.close().

import { setupServer } from 'msw/node'

import { handlers } from './handlers'

export const server = setupServer(...handlers)
