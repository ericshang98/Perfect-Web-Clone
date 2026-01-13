/**
 * Project Naming API
 *
 * Simple API to generate project names using AI.
 * Uses haiku model for fast, low-cost naming.
 */

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:5100";

/**
 * Generate a project name based on user intent
 *
 * @param userMessage - The first message from the user
 * @returns A short project name (2-5 words)
 */
export async function generateProjectName(userMessage: string): Promise<string> {
  try {
    const response = await fetch(`${API_BASE}/api/project-name`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ message: userMessage }),
    });

    if (!response.ok) {
      console.error("[ProjectNaming] API error:", response.status);
      return "";
    }

    const data = await response.json();
    return data.name || "";
  } catch (error) {
    console.error("[ProjectNaming] Failed to generate name:", error);
    return "";
  }
}
