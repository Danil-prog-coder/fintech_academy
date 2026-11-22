export type Role = 'owner' | 'admin' | 'support' | 'user';

export interface Project {
  id: string;
  name: string;
  role: Role;
  created_at: string;
}

export interface ProjectsResponse {
  projects: Project[];
  current_project_id: string | null;
}

export interface CreatedProject {
  project: Project;
  /** Код проекта показывается один раз: с ним, логином и паролем входят на сайт администратора. */
  project_code: string;
  owner_panel_setup_url: string;
}

export interface Member {
  external_id: string;
  role: Role;
  email: string | null;
  display_name: string | null;
  allowed_sections: string[] | null;
  panel_login: string | null;
  panel_password_set: boolean;
}

export interface Section {
  slug: string;
  title: string;
}

export interface MemberPut {
  email: string;
  role: Exclude<Role, 'owner'>;
  login?: string;
  allowed_sections?: string[] | null;
  keep_sections?: boolean;
}
