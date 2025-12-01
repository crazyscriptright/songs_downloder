// API Configuration
// Auto-detects environment and sets appropriate API URL
const API_BASE_URL =
  window.location.hostname === "localhost" ||
  window.location.hostname === "127.0.0.1"
    ? "http://localhost:5000"
    : "https://song-download-9889cf8e8f85.herokuapp.com";

// Helper function to make API calls
async function apiCall(endpoint, options = {}) {
  const url = `${API_BASE_URL}${endpoint}`;
  const response = await fetch(url, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...options.headers,
    },
  });
  return response;
}

// Export for use in index.html and bulk.html
window.API_BASE_URL = API_BASE_URL;
window.API = {
  baseUrl: API_BASE_URL,
  call: apiCall,
};
