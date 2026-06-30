export interface AuditEvent {
  id: string;
  actor: string;
  action: string;
  target: string;
  timestamp: string;
}

export interface AuditPage {
  events: AuditEvent[];
  total: number;
}
