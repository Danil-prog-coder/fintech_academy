export interface DemoInfo {
  enabled: boolean;
  label: string;
}

export interface Credentials {
  email: string;
  password: string;
}

export interface Me {
  id: number;
  email: string;
  /** Вошли через «Тестовый доступ»: общий демо-аккаунт. */
  demo?: boolean;
  repo_status: string;
}
