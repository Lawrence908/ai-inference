"""
title: Context Pack RAG Tool
author: Chris Lawrence
description: Search and retrieve context from personal RAG API (chat history, skills, docs)
required_open_webui_version: 0.5.0
version: 1.0.0
"""

import httpx
from typing import Optional, List
from pydantic import BaseModel


class Tools:
    def __init__(self):
        self.valves = self.Valves()
        # Context Pack API base URL (accessible via Docker network)
        self.context_api_url = "http://context-pack:8000"

    class Valves(BaseModel):
        context_api_url: str = "http://context-pack:8000"
        default_k: int = 6  # Number of chunks to retrieve
        default_namespace: Optional[str] = None  # Optional namespace filter

    async def search_context(
        self,
        query: str,
        k: int = 6,
        namespace: Optional[str] = None,
        sensitivity: str = "public",
        __event_emitter__=None,
    ) -> str:
        """
        Search your personal context (chat history, skills, docs) using FTS.
        
        :param query: Search query (supports FTS MATCH syntax, e.g., "(azure AND api)")
        :param k: Number of chunks to retrieve (default: 6)
        :param namespace: Optional namespace filter (e.g., "core", "skills", "projects/magic-pages")
        :param sensitivity: Sensitivity level - "public", "internal", or "private" (default: "public")
        """
        api_url = self.valves.context_api_url or self.context_api_url
        
        if __event_emitter__:
            await __event_emitter__({
                "type": "status",
                "data": {"description": f"Searching context for: {query[:50]}...", "done": False}
            })

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                params = {
                    "q": query,
                    "k": k or self.valves.default_k,
                }
                if namespace or self.valves.default_namespace:
                    params["namespace"] = namespace or self.valves.default_namespace
                if sensitivity:
                    params["sensitivity"] = sensitivity

                response = await client.get(f"{api_url}/search", params=params)
                response.raise_for_status()
                results = response.json()

                if __event_emitter__:
                    await __event_emitter__({
                        "type": "status",
                        "data": {"description": f"Found {len(results)} relevant chunks", "done": True}
                    })

                if not results:
                    return f"No results found for query: {query}"

                # Format results for LLM consumption
                formatted = "### Retrieved Context\n\n"
                for i, result in enumerate(results, 1):
                    formatted += f"#### Result {i}: {result.get('title', 'Untitled')}\n"
                    formatted += f"**Namespace**: {result.get('namespace', 'unknown')}\n"
                    formatted += f"**Content**:\n{result.get('text', '')}\n\n---\n\n"

                return formatted

        except httpx.HTTPError as e:
            error_msg = f"Error connecting to Context Pack API: {str(e)}"
            if __event_emitter__:
                await __event_emitter__({
                    "type": "status",
                    "data": {"description": error_msg, "done": True}
                })
            return error_msg
        except Exception as e:
            error_msg = f"Unexpected error: {str(e)}"
            if __event_emitter__:
                await __event_emitter__({
                    "type": "status",
                    "data": {"description": error_msg, "done": True}
                })
            return error_msg

    async def generate_with_context(
        self,
        prompt: str,
        k: int = 6,
        namespace: Optional[str] = None,
        sensitivity: str = "public",
        model: str = "none",
        __event_emitter__=None,
    ) -> str:
        """
        Generate a response using RAG from your personal context.
        
        :param prompt: Your question or task
        :param k: Number of context chunks to retrieve (default: 6)
        :param namespace: Optional namespace filter
        :param sensitivity: Sensitivity level - "public", "internal", or "private"
        :param model: Model to use for generation (e.g., "openai:gpt-4o-mini") or "none" to return prompt only
        """
        api_url = self.valves.context_api_url or self.context_api_url
        
        if __event_emitter__:
            await __event_emitter__({
                "type": "status",
                "data": {"description": "Retrieving context and generating response...", "done": False}
            })

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                payload = {
                    "prompt": prompt,
                    "k": k or self.valves.default_k,
                    "sensitivity": sensitivity,
                    "model": model,
                }
                if namespace or self.valves.default_namespace:
                    payload["namespace"] = namespace or self.valves.default_namespace

                response = await client.post(f"{api_url}/generate", json=payload)
                response.raise_for_status()
                result = response.json()

                if __event_emitter__:
                    await __event_emitter__({
                        "type": "status",
                        "data": {"description": "Generation complete", "done": True}
                    })

                if result.get("output"):
                    return result["output"]
                elif result.get("prompt_sent"):
                    return f"**Assembled Prompt (model disabled)**:\n\n{result['prompt_sent']}"
                else:
                    return f"Generation completed. Note: {result.get('note', 'No output generated')}"

        except httpx.HTTPError as e:
            error_msg = f"Error connecting to Context Pack API: {str(e)}"
            if __event_emitter__:
                await __event_emitter__({
                    "type": "status",
                    "data": {"description": error_msg, "done": True}
                })
            return error_msg
        except Exception as e:
            error_msg = f"Unexpected error: {str(e)}"
            if __event_emitter__:
                await __event_emitter__({
                    "type": "status",
                    "data": {"description": error_msg, "done": True}
                })
            return error_msg

    async def list_skills(
        self,
        __event_emitter__=None,
    ) -> str:
        """
        List all available skills from your context pack.
        """
        api_url = self.valves.context_api_url or self.context_api_url
        
        if __event_emitter__:
            await __event_emitter__({
                "type": "status",
                "data": {"description": "Fetching available skills...", "done": False}
            })

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(f"{api_url}/skills")
                response.raise_for_status()
                skills = response.json()

                if __event_emitter__:
                    await __event_emitter__({
                        "type": "status",
                        "data": {"description": f"Found {len(skills)} skills", "done": True}
                    })

                if not skills:
                    return "No skills found in context pack."

                formatted = "### Available Skills\n\n"
                by_category = {}
                for skill in skills:
                    category = skill.get("category", "uncategorized")
                    if category not in by_category:
                        by_category[category] = []
                    by_category[category].append(skill)

                for category, skill_list in sorted(by_category.items()):
                    formatted += f"#### {category.title()}\n"
                    for skill in skill_list:
                        name = skill.get("name", "unknown")
                        desc = skill.get("description", "No description")
                        path = skill.get("path", "")
                        formatted += f"- **{name}** ({path}): {desc}\n"
                    formatted += "\n"

                return formatted

        except httpx.HTTPError as e:
            return f"Error connecting to Context Pack API: {str(e)}"
        except Exception as e:
            return f"Unexpected error: {str(e)}"

    async def generate_with_skills(
        self,
        prompt: str,
        skills: List[str] = [],
        bundle: Optional[str] = None,
        k: int = 6,
        namespace: Optional[str] = None,
        sensitivity: str = "public",
        model: str = "none",
        __event_emitter__=None,
    ) -> str:
        """
        Generate a response with specific skills pre-loaded and optional RAG context.
        
        :param prompt: Your question or task
        :param skills: List of skill paths (e.g., ["infra/homelab-change-plan", "dev/docker-compose-editing"])
        :param bundle: Optional bundle name (e.g., "homelab-setup")
        :param k: Number of RAG chunks to retrieve (default: 6, set to 0 to disable RAG)
        :param namespace: Optional namespace filter for RAG
        :param sensitivity: Sensitivity level for RAG
        :param model: Model to use or "none" to return prompt only
        """
        api_url = self.valves.context_api_url or self.context_api_url
        
        if __event_emitter__:
            await __event_emitter__({
                "type": "status",
                "data": {"description": "Loading skills and generating response...", "done": False}
            })

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                payload = {
                    "prompt": prompt,
                    "skills": skills or [],
                    "k": k or self.valves.default_k,
                    "sensitivity": sensitivity,
                    "model": model,
                }
                if bundle:
                    payload["bundle"] = bundle
                if namespace or self.valves.default_namespace:
                    payload["namespace"] = namespace or self.valves.default_namespace

                response = await client.post(f"{api_url}/generate-with-skills", json=payload)
                response.raise_for_status()
                result = response.json()

                if __event_emitter__:
                    await __event_emitter__({
                        "type": "status",
                        "data": {"description": "Generation complete", "done": True}
                    })

                output_parts = []
                if result.get("skills_loaded"):
                    output_parts.append(f"**Skills Loaded**: {', '.join(result['skills_loaded'])}")
                if result.get("rag_chunks_used", 0) > 0:
                    output_parts.append(f"**RAG Chunks Used**: {result['rag_chunks_used']}")

                if result.get("output"):
                    if output_parts:
                        return f"{' | '.join(output_parts)}\n\n{result['output']}"
                    return result["output"]
                elif result.get("prompt_sent"):
                    header = f"{' | '.join(output_parts)}\n\n" if output_parts else ""
                    return f"{header}**Assembled Prompt (model disabled)**:\n\n{result['prompt_sent']}"
                else:
                    return f"Generation completed. Note: {result.get('note', 'No output generated')}"

        except httpx.HTTPError as e:
            error_msg = f"Error connecting to Context Pack API: {str(e)}"
            if __event_emitter__:
                await __event_emitter__({
                    "type": "status",
                    "data": {"description": error_msg, "done": True}
                })
            return error_msg
        except Exception as e:
            error_msg = f"Unexpected error: {str(e)}"
            if __event_emitter__:
                await __event_emitter__({
                    "type": "status",
                    "data": {"description": error_msg, "done": True}
                })
            return error_msg

