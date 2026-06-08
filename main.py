import os
import re
import operator
import argparse
import sys
from typing import Annotated, List, TypedDict, Literal, Optional, Tuple, Union

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage, AIMessage
from langgraph.graph import StateGraph, END
from dotenv import load_dotenv

load_dotenv()

# 1. Setup the LLM
llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash")

# 2. Utility: Bulletproof Link Normalization
def normalize_wiki_links(text: str) -> str:
    """Cross-references [[wiki-links]] against actual filenames in output/ and forces exact matches using alphanumeric normalization and alias handling."""
    output_dir = "output"
    if not os.path.exists(output_dir):
        return text
    
    # 1. Build a Clean Alphanumeric Dictionary
    existing_files = [f for f in os.listdir(output_dir) if f.endswith(".md")]
    
    def alpha_norm(s: str) -> str:
        # Strip .md if it exists, remove non-alphanumeric, and lowercase
        base = s[:-3] if s.lower().endswith(".md") else s
        return re.sub(r'[^a-zA-Z0-9]', '', base).lower()
    
    # Map alphanumeric key to EXACT base filename (without .md)
    norm_map = {}
    for f in existing_files:
        base_name = f[:-3] # Remove .md
        norm_map[alpha_norm(base_name)] = base_name
    
    # 2. Parse Links Safely (Handling Aliases)
    def replacement(match):
        raw_inner = match.group(1)
        
        # Split target and alias
        if "|" in raw_inner:
            target, alias = raw_inner.split("|", 1)
        else:
            target, alias = raw_inner, None
            
        # 3. Resolve and Reconstruct
        norm_target = alpha_norm(target)
        
        if norm_target in norm_map:
            resolved_target = norm_map[norm_target]
        else:
            # Fallback: standardize new nodes with underscores
            resolved_target = target.strip().replace(" ", "_")
            
        if alias:
            return f"[[{resolved_target}|{alias}]]"
        return f"[[{resolved_target}]]"

    return re.sub(r"\[\[(.*?)\]\]", replacement, text)

# 3. Hardened File-Writing Tool
def write_world_asset(filename: str, title: str, content: str, entity_type: str, mode: str = "exploratory"):
    """Writes or overwrites markdown content with strict taxonomy tags and normalization."""
    os.makedirs("output", exist_ok=True)
    path = os.path.join("output", f"{filename}.md")
    
    sanitized_type = entity_type.strip().lower().replace(" ", "_").replace("#", "").replace("type/", "")
    tag = f"#type/{sanitized_type}"
    
    # Clean the content: Normalize links and strip existing tags
    clean_content = normalize_wiki_links(content)
    clean_content = re.sub(r"#type/\w+", "", clean_content).strip()
    
    # Final Write: OVERWRITE SCHEMA
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"# {title}\n\n")
        f.write(clean_content)
        f.write(f"\n\n{tag}")
            
    discovered_links = []
    # Link extraction ONLY in exploratory mode
    if mode == "exploratory":
        links = re.findall(r"\[\[(.*?)\]\]", clean_content)
        discovered_links = [{"name": link, "type": "lore", "parent": title} for link in links]
        
    return path, discovered_links

def get_missing_links(links: List[dict]) -> List[dict]:
    missing = []
    for link in links:
        filename = link["name"].replace(" ", "_").replace("/", "_")
        if not os.path.exists(os.path.join("output", f"{filename}.md")):
            missing.append(link)
    return missing

# 4. Global Chronicle Management (QUARANTINED)
CHRONICLE_PATH = "output/world_chronicle.md"
def ensure_chronicle():
    os.makedirs("output", exist_ok=True)
    if not os.path.exists(CHRONICLE_PATH):
        with open(CHRONICLE_PATH, "w", encoding="utf-8") as f:
            f.write("# Global World Chronicle\n\nMaster ledger of established facts, factions, history, and regional states.\n")

def read_chronicle() -> str:
    ensure_chronicle()
    with open(CHRONICLE_PATH, "r", encoding="utf-8") as f: return f.read()

def update_chronicle(new_facts: str):
    ensure_chronicle()
    if not new_facts.strip(): return
    existing = read_chronicle()
    if new_facts.strip() in existing: return
    with open(CHRONICLE_PATH, "a", encoding="utf-8") as f: f.write(f"\n\n### New Developments\n{new_facts}")

# 5. Agent State
class PendingLink(TypedDict):
    name: str
    type: str
    parent: str

class AgentState(TypedDict):
    messages: Annotated[List[BaseMessage], operator.add]
    current_region: str
    pending_links: List[PendingLink]
    next_node: str
    inspiration_context: str
    last_generated_content: str
    last_generated_title: str
    last_generated_filename: str
    last_generated_type: str
    generation_mode: Literal["exploratory", "isolated", "fill"]

# 6. Nodes
def inspiration_researcher(state: AgentState):
    print("\n--- [InspirationResearcher] Researching Thematic Context ---")
    messages = state.get("messages", [])
    last_message = messages[-1].content if messages else "a generic setting"
    match = re.search(r"(?:inspired by|similar to|inspiration:)\s+(.+?)(?:$|\.|\s+and)", last_message, re.IGNORECASE)
    target = match.group(1) if match else "a generic setting"
    prompt = f"Research thematic reference: '{target}'. Focus on Aesthetic, Factions, Culture, Structure."
    response = llm.invoke([HumanMessage(content=prompt)])
    return {"inspiration_context": response.content, "next_node": "supervisor"}

def supervisor(state: AgentState):
    messages = state.get("messages", [])
    if not messages: return {"next_node": "GenericBuilder", "last_generated_type": "region"}
    last_message_raw = messages[-1].content
    
    if any(phrase in last_message_raw.lower() for phrase in ["inspired by", "similar to"]) and not state.get("inspiration_context"):
        return {"next_node": "InspirationResearcher"}
    
    taxonomy = "region, city, character, faction, phenomena, artifact, event, lore"
    prompt = f"Classify world-building request: {taxonomy}. Respond ONLY with the word.\nREQUEST: {last_message_raw}"
    
    decision = None
    prefixes = {
        "Region:": "region", "City:": "city", "Character:": "character", "Faction:": "faction",
        "Phenomena:": "phenomena", "Artifact:": "artifact", "Event:": "event", "Lore:": "lore"
    }
    for prefix, tag in prefixes.items():
        if last_message_raw.startswith(prefix):
            decision = tag
            break
    if not decision:
        decision = llm.invoke([HumanMessage(content=prompt)]).content.strip().lower()
    
    parent_match = re.search(r"in \[\[(.*?)\]\]", last_message_raw)
    parent_name = parent_match.group(1) if parent_match else state.get("current_region", "The Known World")
    
    def check_parent_exists(name: str) -> bool:
        if name == "The Known World": return True
        return os.path.exists(os.path.join("output", f"{name.replace(' ', '_')}.md"))

    if decision in ["character", "faction", "phenomena", "city"]:
        if not check_parent_exists(parent_name):
            print(f"--- HIERARCHY BRAKE: Parent [[{parent_name}]] missing. Building parent first. ---")
            parent_type_prompt = f"What is the type of [[{parent_name}]] (region or city)? Respond with ONLY the word."
            ptype = llm.invoke([HumanMessage(content=parent_type_prompt)]).content.strip().lower()
            return {
                "next_node": "GenericBuilder",
                "last_generated_type": ptype if ptype in ["region", "city"] else "region",
                "current_region": "The Known World",
                "last_generated_title": parent_name
            }

    name = re.sub(r"in \[\[.*?\]\]", "", last_message_raw.split(":", 1)[1] if ":" in last_message_raw[:15] else last_message_raw).strip()
    return {
        "next_node": "GenericBuilder",
        "last_generated_type": decision,
        "current_region": parent_name,
        "last_generated_title": name
    }

def generic_builder(state: AgentState):
    etype = state["last_generated_type"]
    name = state["last_generated_title"]
    parent = state["current_region"]
    mode = state.get("generation_mode", "exploratory")
    
    print(f"\n--- [GenericBuilder] Generating {etype.capitalize()}: {name} (Anchor: [[{parent}]], Mode: {mode}) ---")
    
    specs = {
        "region": "Specializing in geography, climate, and large-scale atmosphere.",
        "city": f"Specializing in urban layout and economy. MUST explicitly declare and link to the parent [[{parent}]] region you belong to.",
        "character": f"Specializing in NPC profiles. MUST explicitly anchor this character to a home [[{parent}]]. If the character is a wanderer, they must be explicitly tethered to a broader [[{parent}]] boundary.",
        "faction": f"Specializing in organizations. MUST explicitly define and link the core territories, cities, or regions like [[{parent}]] where this faction operates and commands influence."
    }
    
    system = f"You are a world-building assistant {specs.get(etype, 'Specializing in creative world-building.')} "
    if mode == "isolated":
        system += "ISOLATED EDIT MODE ACTIVE. Update the target file. Do NOT introduce new uncreated entities. "
    elif mode == "fill":
        system += "FILL MODE ACTIVE. Flesh out this specific asset using history and parent context. Do NOT generate new [[wiki-links]]. "
    else:
        system += f"Strict Requirement: Anchor this entity within [[{parent}]]. "
        
    system += "Always use [[wiki-links]] for established entities. Ensure links match existing filenames exactly."
    
    if state.get("inspiration_context"):
        system += f"\n\nTHEMATIC GUIDELINES:\n{state['inspiration_context']}"
        
    messages = [SystemMessage(content=system)] + state["messages"]
    if not isinstance(messages[-1], HumanMessage):
        messages.append(HumanMessage(content=f"Build the {etype}: {name}"))
        
    response = llm.invoke(messages)
    return {
        "last_generated_content": response.content,
        "last_generated_title": name,
        "last_generated_filename": name.replace(" ", "_"),
        "next_node": "ContinuityValidator"
    }

def continuity_validator(state: AgentState):
    print("\n--- [ContinuityValidator] Checking Lore Consistency ---")
    chronicle = read_chronicle()
    
    # 1. XML Separation of Concerns
    system_prompt = (
        "You are a master historian and continuity editor. "
        "Review the NEW WORLD CONTENT against the provided reference lore. "
        "Your output must follow this rigid XML structural pattern:\n"
        "1. Any major historical developments or new facts to be added to the chronicle must be enclosed in <chronicle_append> tags.\n"
        "2. The clean, validated, and updated asset description must be enclosed in <validated_content> tags.\n\n"
        "Rules:\n"
        "- Resolve any contradictions found in the new content.\n"
        "- Ensure the asset remains anchored in its parent context.\n"
        "- Do not include the reference lore in your validated content."
    )
    
    prompt = (
        f"<established_lore_reference>\n{chronicle[:4000]}\n</established_lore_reference>\n\n"
        f"NEW WORLD CONTENT:\n{state['last_generated_content']}\n\n"
        f"ENTITY: {state['last_generated_title']} ({state['last_generated_type']})\n"
        f"PARENT: {state['current_region']}"
    )
    
    response = llm.invoke([SystemMessage(content=system_prompt), HumanMessage(content=prompt)])
    full_text = response.content
    
    # Parse XML tags
    chronicle_match = re.search(r"<chronicle_append>(.*?)</chronicle_append>", full_text, re.DOTALL)
    content_match = re.search(r"<validated_content>(.*?)</validated_content>", full_text, re.DOTALL)
    
    if chronicle_match:
        update_chronicle(chronicle_match.group(1).strip())
    
    if content_match:
        validated_content = content_match.group(1).strip()
    else:
        print("--- WARNING: XML tags failed to generate. Returning raw response. ---")
        validated_content = full_text

    # Final Write handles clean overwrite and link normalization
    path, new_links = write_world_asset(
        state["last_generated_filename"], 
        state["last_generated_title"], 
        validated_content, 
        state["last_generated_type"],
        mode=state.get("generation_mode", "exploratory")
    )
    print(f"Asset written to {path}")
    
    missing = get_missing_links(new_links)
    return {
        "messages": [AIMessage(content=validated_content)],
        "pending_links": missing,
        "next_node": END
    }

# 7. Build Graph
workflow = StateGraph(AgentState)
workflow.add_node("supervisor", supervisor); workflow.add_node("InspirationResearcher", inspiration_researcher)
workflow.add_node("GenericBuilder", generic_builder); workflow.add_node("ContinuityValidator", continuity_validator)

workflow.set_entry_point("supervisor")
workflow.add_conditional_edges("supervisor", lambda x: x["next_node"], {"InspirationResearcher": "InspirationResearcher", "GenericBuilder": "GenericBuilder", END: END})
workflow.add_conditional_edges("InspirationResearcher", lambda x: x["next_node"], {"supervisor": "supervisor"})
workflow.add_edge("GenericBuilder", "ContinuityValidator")
workflow.add_edge("ContinuityValidator", END)
app = workflow.compile()

# 8. Migration Tool & System Auditor (Systemic Repair Loop)
def migrate_assets(mode: str = "isolated"):
    """Audits and consolidates the world state on disk with XML parsing and failsafes."""
    print(f"\n--- Starting Core Systems Audit (Mode: {mode}) ---")
    output_dir = "output"
    if not os.path.exists(output_dir): return
    
    updated_count = 0
    files = [f for f in os.listdir(output_dir) if f.endswith(".md") and f not in ["world_chronicle.md", "temp.md"]]
    chronicle = read_chronicle()
    
    for filename in files:
        path = os.path.join(output_dir, filename)
        if not os.path.exists(path): continue
        title = filename.replace(".md", "")
        with open(path, "r", encoding="utf-8") as f: raw_content = f.read()
        
        clean_content = raw_content
        # Remove markdown header duplication
        clean_content = re.sub(r"^# .*\n+", "", clean_content).strip()
        
        # 1. Hardened Chronicle Leak Detection
        if "GLOBAL CHRONICLE" in clean_content or "### New Developments" in clean_content or len(clean_content) > 10000:
            print(f"--- DETECTED POTENTIAL LEAK: {title}. Extracting clean asset... ---")
            extraction_prompt = (
                f"The file for '{title}' contains leaked chronicle data or duplicated text. "
                "Surgically extract ONLY the specific description and details for this asset. "
                "Wrap your extraction in <extracted_asset> tags. "
                "If the content is invalid or missing, say 'cannot fulfill'."
                f"\n\nCONTENT:\n{clean_content[:5000]}"
            )
            response = llm.invoke([HumanMessage(content=extraction_prompt)])
            extracted_match = re.search(r"<extracted_asset>(.*?)</extracted_asset>", response.content, re.DOTALL)
            
            # THE FAILSAFE
            if not extracted_match:
                print(f"--- FAILSAFE: Missing <extracted_asset> tag for {title}. Aborting write. ---")
                continue
            
            extracted_text = extracted_match.group(1).strip()
            if len(extracted_text) < 100 or "cannot fulfill" in extracted_text.lower():
                print(f"--- FAILSAFE: Extraction for {title} invalid or too short. Aborting write. ---")
                continue
                
            clean_content = extracted_text

        # 2. Identify Type (Strict Taxonomy)
        asset_type = "region"
        if title == "The_Known_World": asset_type = "root"
        else:
            tag_match = re.search(r"#type/(\w+)", clean_content)
            if tag_match: asset_type = tag_match.group(1)
            else:
                prompt = f"Classify world asset '{title}' as: region, city, character, faction, phenomena, artifact. Respond ONLY one word.\n\nCONTENT:\n{clean_content[:500]}"
                asset_type = llm.invoke([HumanMessage(content=prompt)]).content.strip().lower()

        # 3. Structural Anchoring
        if asset_type in ["city", "character", "faction", "phenomena"] and "in [[" not in clean_content[:500]:
            print(f"--- ANCHORING ORPHAN: {title} ---")
            anchor_prompt = f"Identify parent for '{title}' from history. Respond with ONLY [[Name]].\n\nCHRONICLE:\n{chronicle[:2000]}"
            parent = llm.invoke([HumanMessage(content=anchor_prompt)]).content.strip()
            clean_content = f"Located in {parent}\n\n" + clean_content

        # 4. Final Write (Force Overwrite)
        write_world_asset(title, title, clean_content, asset_type, mode=mode)
        updated_count += 1
        print(f"CONSOLIDATED: [[{title}]] -> #type/{asset_type}")

    print(f"\nAUDIT COMPLETE. {updated_count} files successfully consolidated.")
    sys.exit(0)

# 9. Command Helpers
def run_engine_command(etype: str, name: str, context: Optional[str] = None, inspiration: Optional[str] = None, mode: str = "exploratory"):
    ensure_chronicle()
    state = {"messages": [], "current_region": context or "The Known World", "pending_links": [], "inspiration_context": "", "generation_mode": mode}
    if inspiration:
        state["messages"].append(HumanMessage(content=f"Inspiration: {inspiration}"))
        res = app.invoke(state)
        state.update({k: res[k] for k in ["inspiration_context", "pending_links", "messages"] if k in res})
    
    command = f"{etype.capitalize()}: {name}"
    if context: command += f" in [[{context}]]"
    state["messages"].append(HumanMessage(content=command))
    result = app.invoke(state)
    print(f"\nSUCCESS: [[{name}]] compiled (#type/{etype}).")

def run_expansion(n: int, mode: str = "exploratory"):
    ensure_chronicle()
    chronicle = read_chronicle()
    _, pending = write_world_asset("temp", "temp", chronicle, "lore", mode="exploratory")
    if os.path.exists("output/temp.md"): os.remove("output/temp.md")
    
    state = {"messages": [], "current_region": "The Known World", "pending_links": pending, "inspiration_context": "", "generation_mode": mode}
    for i in range(n):
        if not state["pending_links"]: break
        link = state["pending_links"].pop(0)
        name, etype, parent = link["name"], link["type"], link["parent"]
        print(f"\n--- Expanding: [[{name}]] ({etype}) ---")
        command = f"{etype.capitalize()}: {name} in [[{parent}]]"
        state["messages"].append(HumanMessage(content=command))
        result = app.invoke(state)
        if mode == "exploratory":
            new_links = result.get("pending_links", [])
            for nl in new_links:
                if nl["name"] not in [p["name"] for p in state["pending_links"]]: state["pending_links"].append(nl)
    print("\nEXPANSION COMPLETE.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    types = ["region", "city", "character", "faction", "guild", "phenomena", "institution", "lineage", "economy", "flora_fauna", "artifact", "event", "lore"]
    for t in types: parser.add_argument(f"--{t}", type=str)
    parser.add_argument("--context", type=str)
    parser.add_argument("--inspiration", type=str); parser.add_argument("--expand", type=int)
    parser.add_argument("--mode", choices=["exploratory", "isolated", "fill"], default="exploratory")
    parser.add_argument("--migrate", action="store_true")
    args = parser.parse_args()
    
    if args.migrate: migrate_assets(mode=args.mode)
    for t in types:
        val = getattr(args, t.replace("-", "_"))
        if val:
            run_engine_command(t, val, context=args.context, inspiration=args.inspiration, mode=args.mode)
            sys.exit(0)
    if args.expand: run_expansion(args.expand, mode=args.mode)
    else: print("Use --[type], --expand, or --migrate.")
