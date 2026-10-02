export interface AccountProfile {
  username: string
  role: string
  display_name: string
  organization: string
  default_community_id: string | null
  text_size: 'comfortable' | 'large'
  reduced_motion: boolean
  revision: number
  updated_at: string | null
  authentication_mode: 'development'
}
export interface AccountActivity {
  community_count: number; drill_count: number; completed_count: number; unfinished_count: number
  recent: { id: string; scene_id: string; community_id: string; community_name: string; name: string; status: string; created_at: string; score: number | null }[]
}
