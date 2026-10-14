export interface ConfigurationIssue {
  key: string
  message: string
  target: 'scenes'
  query: { scene: string; field: string; preparation: string }
}
export interface ConfigurationValidation {
  passed: boolean
  issues: string[]
  issue_details: ConfigurationIssue[]
  message: string
}
