export interface KnowledgeHit {
  match?:KnowledgeMatch
  applicability?:KnowledgeApplicability
  experience?:KnowledgeObservation
  id: string; document_id: string; version_id: string; version: number; chunk_id: string
  title: string; anchor: string; content: string; content_hash: string; source_url: string
  publisher: string; category: string; scenario: string
}
export interface KnowledgeMatch {
  method:'keyword'|'semantic'|'hybrid';terms:string[];expanded_terms:string[];ranking_revision:string
}
export interface KnowledgeResult { retrieval_id: string; retrieved_at?:string; method: string; notice: string; hits: KnowledgeHit[];assessment?:KnowledgeAssessment }
export interface KnowledgeApplicability {
  status:'different'|'matched'|'unchecked'|'unverified';label:string;notice:string;at_seconds?:number;event_sequence?:number
  differences:Array<{field:string;label:string;recorded:string|number;current:string|number}>;missing:string[]
}
export interface KnowledgeAssessment {
  experience_count:number;matched_count:number;excluded_citations:string[];notice:string
  items:Array<Partial<KnowledgeApplicability>&{id:string;title:string}>
}
export interface KnowledgeVersion {
  id: string; number: number; status: string; failure: string; filename: string; extraction: string
  reviewer: string | null; reviewed_at: string | null; embedding_model: string | null
  text?: string
  valid_until?: string | null; effective_status?: string
  chunks?: KnowledgeChunk[]
}
export interface KnowledgeChunk { id:string;anchor:string;content:string;content_hash:string }
export interface KnowledgeDocument {
  experience?:KnowledgeObservation
  id: string; title: string; category: string; scenario: string; source_url: string; publisher: string
  community_id: string | null; builtin: boolean; versions: KnowledgeVersion[]
}
export interface KnowledgeObservation {
  kind?:'simulation_observation'|'simulation_archive';run_id?:string|null;archive_id?:string;result_kind?:string;drill_id:string;community_id?:string;scene_id?:string;scene_version_id:string|null
  revision?:number|null;observed_at:number;forecast_at?:number;approved_at?:number;forecast_seconds?:number;population:number
  title?:string;drill_name?:string;goal?:string;basis_hash:string;intervention_count:number
  predicted?:{arrived:number;exposed:number;queue_seconds:number}|null;actual:{arrived:number;exposed:number;queue_seconds:number}
  delta?:{arrived:number;exposed:number;queue_seconds:number}
  event_sequence_from?:number;event_sequence_to?:number;parameters?:Record<string,string|number>
  forecast_engine_revision?:number|string|null;observed_engine_revision?:number|string|null
  events?:Array<{id:string;sequence:number;at_seconds:number;kind:string;message:string}>
}
