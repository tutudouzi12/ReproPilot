import { httpClient } from './httpClient';

export interface ApiAuthStatus {
  enabled: boolean;
  authenticated: boolean;
}

export const getApiAuthStatus = async (): Promise<ApiAuthStatus> => {
  const response = await httpClient.get<ApiAuthStatus>('/api/auth/status');
  return response.data;
};

export const createApiAuthSession = async (token: string): Promise<ApiAuthStatus> => {
  const response = await httpClient.post<ApiAuthStatus>('/api/auth/session', { token });
  return response.data;
};
