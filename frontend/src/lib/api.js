/**
 * API Client for FDC Tax Core
 * Handles authentication and API requests
 */

import axios from 'axios';

const API_BASE = process.env.REACT_APP_BACKEND_URL;
const API = `${API_BASE}/api`;

// Create axios instance
const apiClient = axios.create({
  baseURL: API,
  headers: {
    'Content-Type': 'application/json',
  },
});

// Add auth token to requests
apiClient.interceptors.request.use((config) => {
  const token = localStorage.getItem('access_token');
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// Handle auth errors
apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    // Only redirect on 401 if not on login page (to allow login error messages to display)
    if (error.response?.status === 401 && !window.location.pathname.includes('/login')) {
      localStorage.removeItem('access_token');
      localStorage.removeItem('user');
      window.location.href = '/login';
    }
    return Promise.reject(error);
  }
);

// Auth API
export const authApi = {
  login: async (email, password) => {
    const response = await apiClient.post('/auth/login', { email, password });
    return response.data;
  },
  logout: () => {
    localStorage.removeItem('access_token');
    localStorage.removeItem('user');
  },
};

// Ingestion API
export const ingestionApi = {
  // Upload file
  uploadFile: async (file, clientId, jobId = null) => {
    const formData = new FormData();
    formData.append('file', file);
    
    let url = `/ingestion/upload?client_id=${encodeURIComponent(clientId)}`;
    if (jobId) {
      url += `&job_id=${encodeURIComponent(jobId)}`;
    }
    
    const response = await apiClient.post(url, formData, {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
    });
    return response.data;
  },

  // Parse file
  parseFile: async (batchId) => {
    const response = await apiClient.post('/ingestion/parse', { batch_id: batchId });
    return response.data;
  },

  // Import transactions
  importTransactions: async (batchId, columnMapping, skipDuplicates = true) => {
    const response = await apiClient.post('/ingestion/import', {
      batch_id: batchId,
      column_mapping: columnMapping,
      skip_duplicates: skipDuplicates,
    });
    return response.data;
  },

  // Rollback batch
  rollbackBatch: async (batchId) => {
    const response = await apiClient.post('/ingestion/rollback', { batch_id: batchId });
    return response.data;
  },

  // List batches
  listBatches: async (filters = {}) => {
    const params = new URLSearchParams();
    if (filters.clientId) params.append('client_id', filters.clientId);
    if (filters.jobId) params.append('job_id', filters.jobId);
    if (filters.status) params.append('status', filters.status);
    if (filters.limit) params.append('limit', filters.limit);
    if (filters.offset) params.append('offset', filters.offset);
    
    const response = await apiClient.get(`/ingestion/batches?${params.toString()}`);
    return response.data;
  },

  // Get batch details
  getBatch: async (batchId) => {
    const response = await apiClient.get(`/ingestion/batches/${batchId}`);
    return response.data;
  },

  // Get batch audit log
  getBatchAuditLog: async (batchId) => {
    const response = await apiClient.get(`/ingestion/batches/${batchId}/audit-log`);
    return response.data;
  },
};

// CRM/Clients API (simplified - we'll need this for client selection)
export const clientsApi = {
  list: async () => {
    try {
      const response = await apiClient.get('/crm/clients');
      return response.data;
    } catch (error) {
      // Return empty array if endpoint doesn't exist
      console.warn('Clients API not available:', error.message);
      return [];
    }
  },
};

export default apiClient;
