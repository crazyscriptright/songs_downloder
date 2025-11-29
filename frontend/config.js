// API Configuration
// Uses Vite environment variable or defaults
const API_BASE_URL =
  import.meta.env.VITE_API_URL ||
  (window.location.hostname === "localhost"
    ? "http://localhost:5000"
    : "https://song-download-9889cf8e8f85.herokuapp.com");

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

// Export for use in index.html
window.API = {
  baseUrl: API_BASE_URL,
  call: apiCall,
};

console.log("🌐 API Base URL:", API_BASE_URL);
