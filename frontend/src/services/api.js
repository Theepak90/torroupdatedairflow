/**
 * API Client for Data Discovery
 */
import { API_BASE_URL } from '../utils/constants';

const API_ENDPOINTS = {
  DISCOVERIES: `${API_BASE_URL}/api/discovery`,
  DISCOVERY_BY_ID: (id) => `${API_BASE_URL}/api/discovery/${id}`,
  APPROVE: (id) => `${API_BASE_URL}/api/discovery/${id}/approve`,
  REJECT: (id) => `${API_BASE_URL}/api/discovery/${id}/reject`,
  STATS: `${API_BASE_URL}/api/discovery/stats`,
  TRIGGER_DISCOVERY: `${API_BASE_URL}/api/discovery/trigger`,
};

/**
 * Get list of discoveries
 */
export const getDiscoveries = async (params = {}) => {
  const queryParams = new URLSearchParams();
  
  if (params.page !== undefined) queryParams.append('page', params.page);
  if (params.size !== undefined) queryParams.append('size', params.size);
  if (params.status) queryParams.append('status', params.status);
  if (params.environment) queryParams.append('environment', params.environment);
  if (params.data_source_type) queryParams.append('data_source_type', params.data_source_type);
  if (params.search) queryParams.append('search', params.search);
  
  const url = `${API_ENDPOINTS.DISCOVERIES}?${queryParams.toString()}`;
  const response = await fetch(url);
  
  if (!response.ok) {
    throw new Error(`HTTP error! status: ${response.status}`);
  }
  
  return await response.json();
};

/**
 * Get single discovery by ID
 */
export const getDiscoveryById = async (id) => {
  const response = await fetch(API_ENDPOINTS.DISCOVERY_BY_ID(id));
  
  if (!response.ok) {
    throw new Error(`HTTP error! status: ${response.status}`);
  }
  
  return await response.json();
};

/**
 * Approve discovery
 */
export const approveDiscovery = async (id, approvedBy) => {
  const response = await fetch(API_ENDPOINTS.APPROVE(id), {
    method: 'PUT',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ approved_by: approvedBy }),
  });
  
  if (!response.ok) {
    throw new Error(`HTTP error! status: ${response.status}`);
  }
  
  return await response.json();
};

/**
 * Reject discovery
 */
export const rejectDiscovery = async (id, rejectedBy, rejectionReason = null) => {
  const response = await fetch(API_ENDPOINTS.REJECT(id), {
    method: 'PUT',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      rejected_by: rejectedBy,
      rejection_reason: rejectionReason,
    }),
  });
  
  if (!response.ok) {
    throw new Error(`HTTP error! status: ${response.status}`);
  }
  
  return await response.json();
};

/**
 * Get summary statistics
 */
export const getStats = async () => {
  const response = await fetch(API_ENDPOINTS.STATS);
  
  if (!response.ok) {
    throw new Error(`HTTP error! status: ${response.status}`);
  }
  
  return await response.json();
};

/**
 * Trigger manual discovery scan
 */
export const triggerDiscovery = async () => {
  const response = await fetch(API_ENDPOINTS.TRIGGER_DISCOVERY, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
  });
  
  if (!response.ok) {
    throw new Error(`HTTP error! status: ${response.status}`);
  }
  
  return await response.json();
};

