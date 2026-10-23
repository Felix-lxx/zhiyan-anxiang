export type CommunityStatus = 'draft' | 'published' | 'archived'
export type VersionStatus = 'draft' | 'validated' | 'published' | 'archived'

export interface CommunityVersion {
  id: string
  version_number: number
  name: string
  status: VersionStatus
}

export interface Community {
  id: string
  name: string
  address: string | null
  description: string | null
  status: CommunityStatus
  created_at: string
  updated_at: string
  owner_username: string
  versions: CommunityVersion[]
}

export interface HealthResponse {
  status: 'healthy' | 'degraded'
  service: string
  environment: string
  database: { status: 'healthy' | 'degraded' }
}

export interface LoginResponse {
  access_token: string
  token_type: string
  expires_in: number
  username: string
  role: string
  role_code: string
}

export interface CurrentUser {
  username: string
  role: string
  role_code?: string
  roles?: string[]
  authentication_mode?: string
}

export interface SceneVersion {
  version_number: number
  parameters: Record<string, string | number>
}

export interface Scene {
  id: string
  name: string
  status: string
  versions: SceneVersion[]
  capabilities?: ScenarioCapabilities
}

export interface ScenarioCapabilities {
  code:string;contract_version:number;title:string;status:'available'|'planned'|'unsupported'
  notice:string;source_types:string[];location_kinds:string[];features:string[]
  parameter_schema:string|null;environment_model:string|null
  can_create:boolean;can_configure:boolean;can_preview:boolean;can_publish:boolean;can_run:boolean
}

export interface SceneTemplate {
  id:string;code:string;name:string;description:string;defaults:Record<string,unknown>
  capabilities:ScenarioCapabilities
}

export interface MapObjectSummary {
  id: string
  name: string
  object_type: string
  floors?: number
}
