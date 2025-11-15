"""
Master Actions Tool - Procedural Actions with Links & Steps
Handles queries about HOW TO perform actions in HR systems (DarwinBox, SumTotal, etc.)
Dynamically loads action guides from Master Document in S3
"""
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field
from crewai.tools import BaseTool
from pydantic import BaseModel, Field
from pathlib import Path
import re
import tempfile
from langchain_community.document_loaders import Docx2txtLoader


@dataclass
class ActionGuide:
    """Structured action with link, steps, and provenance"""
    action_name: str
    link: Optional[str]
    steps: List[str]
    keywords: List[str]  # For matching queries
    source: str = field(default="Master Actions Guide")


class MasterActionsDatabase:
    """Loads structured procedural actions from Master Document"""
    
    def __init__(self, cache_dir: Optional[str] = None):
        """
        Initialize database by loading from Master Document
        
        Args:
            cache_dir: Directory containing cached S3 documents (e.g., /tmp/hr_bot_s3_cache/employee/)
        """
        self.actions: List[ActionGuide] = []
        self._load_from_master_document(cache_dir)
        
        # Fallback: If master doc not found or parsing failed, use minimal hardcoded defaults
        if not self.actions:
            print("⚠️  Master Document not found or empty - using fallback actions")
            self._load_fallback_actions()
    
    def _load_from_master_document(self, cache_dir: Optional[str] = None):
        """
        Parse Master Document (Knowledge Bot – Action Links and Steps.docx) from S3 cache
        
        Expected format in document:
        Action Name: Apply Leave
        Link: https://darwinbox.com/...
        Steps:
        1. Click on the mentioned link
        2. Select 'Apply Leave'
        ...
        Keywords: apply leave, request leave, ...
        """
        try:
            # Find Master Document in cache
            master_doc_path = self._find_master_document(cache_dir)
            if not master_doc_path:
                print("❌ Master Document not found in cache")
                return
            
            print(f"📖 Loading Master Document from: {master_doc_path}")
            
            # Load document content
            loader = Docx2txtLoader(str(master_doc_path))
            docs = loader.load()
            
            if not docs:
                print("❌ Master Document is empty")
                return
            
            content = docs[0].page_content
            source_name = master_doc_path.name
            
            # Parse actions using structured patterns
            self.actions = self._parse_actions(content, source_name)
            print(f"✅ Loaded {len(self.actions)} actions from Master Document")
            
        except Exception as e:
            print(f"❌ Error loading Master Document: {e}")
    
    def _find_master_document(self, cache_dir: Optional[str] = None) -> Optional[Path]:
        """Find Master Document in S3 cache directory"""
        if cache_dir:
            base_path = Path(cache_dir)
        else:
            # Search temp directory
            temp_base = Path(tempfile.gettempdir()) / "hr_bot_s3_cache"
            # Check both employee and executive folders
            for role in ["employee", "executive"]:
                role_path = temp_base / role
                if role_path.exists():
                    base_path = role_path
                    break
            else:
                return None
        
        # Look for Master Document file
        # Try exact name first
        exact_path = base_path / "Knowledge Bot – Action Links and Steps.docx"
        if exact_path.exists():
            return exact_path
        
        # Search for any file with "knowledge" or "action" in name
        for file in base_path.glob("*"):
            if file.is_file() and any(keyword in file.name.lower() for keyword in ["knowledge", "action", "master", "guide"]):
                return file
        
        return None
    
    def _parse_actions(self, content: str, source_name: str = "Master Actions Guide") -> List[ActionGuide]:
        """
        Parse Master Document content into ActionGuide objects
        
        Format:
        Action Name: <name>
        Link: <url>
        Steps:
        1. <step>
        2. <step>
        Keywords: <keyword1>, <keyword2>, ...
        """
        actions = []
        
        # Split by action blocks (look for "Action Name:" pattern)
        blocks = re.split(r'(?=Action Name:)', content, flags=re.IGNORECASE)
        
        for block in blocks:
            if not block.strip():
                continue
            
            # Extract action name
            name_match = re.search(r'Action Name:\s*(.+?)(?:\n|$)', block, re.IGNORECASE)
            if not name_match:
                continue
            action_name = name_match.group(1).strip()
            
            # Extract link
            link_match = re.search(r'Link:\s*(.+?)(?:\n|$)', block, re.IGNORECASE)
            link = link_match.group(1).strip() if link_match else ""
            if link:
                normalized_link = link.lower()
                if normalized_link in {"n/a", "na", "none", "null"}:
                    link = ""
            if link and not re.match(r"https?://", link):
                # Treat non-URL values as navigation hints rather than hyperlinks
                link = link.strip()
            
            # Extract steps (numbered list)
            steps = []
            step_pattern = r'(?:Steps?:|^\s*\d+\.)\s*(.+?)(?=\n\s*\d+\.|\n[A-Z]|$)'
            for match in re.finditer(step_pattern, block, re.MULTILINE | re.DOTALL):
                step_text = match.group(1).strip()
                if step_text and not step_text.startswith("Action Name") and not step_text.startswith("Link") and not step_text.startswith("Keywords"):
                    # Clean numbered prefix if present
                    step_text = re.sub(r'^\d+\.\s*', '', step_text).strip()
                    if step_text:
                        steps.append(step_text)
            
            # Extract keywords
            keywords = []
            keywords_match = re.search(r'Keywords?:\s*(.+?)(?:\n\n|$)', block, re.IGNORECASE | re.DOTALL)
            if keywords_match:
                keywords_text = keywords_match.group(1).strip()
                # Split by comma and clean
                keywords = [kw.strip().lower() for kw in keywords_text.split(',') if kw.strip()]
            
            # If no explicit keywords, derive from action name
            if not keywords:
                keywords = [word.lower() for word in action_name.split() if len(word) > 2]
            
            # Create ActionGuide if we have minimum required data
            if action_name and (link or steps):
                actions.append(ActionGuide(
                    action_name=action_name,
                    link=link or None,
                    steps=steps if steps else ["Please refer to the provided link for detailed steps."],
                    keywords=keywords,
                    source=source_name
                ))
        
        return actions
    
    def _load_fallback_actions(self):
        """Load minimal fallback actions if Master Document parsing fails"""
        self.actions = [
            # Leave Queries
            ActionGuide(
                action_name="Find Leave Policy Document",
                link="https://sap.demo-company.com/home/policies",
                steps=[
                    "Login to SAP Portal",
                    "Go to Home Page",
                    "Scroll to the end of the page",
                    "Click on 'Policies' section",
                    "Open 'Leave Policy' document"
                ],
                keywords=[
                    "leave policy", "policy document", "find policy", "leave rules",
                    "policy", "leave guidelines", "leave documentation"
                ],
                source="Master Actions Fallback"
            ),
            ActionGuide(
                action_name="Check Remaining Leaves",
                link="https://ascent.demo-company.com/leave-management/balance",
                steps=[
                    "Login to Ascent Portal",
                    "Go to 'Leave Management' Module",
                    "Select 'Leave Application'",
                    "Click on 'Leave Balance'",
                    "View Remaining Leave Details"
                ],
                keywords=[
                    "check leaves", "remaining leaves", "leave balance", "leave quota",
                    "how much leave", "available leave", "leave entitlement", "days left"
                ],
                source="Master Actions Fallback"
            ),
            ActionGuide(
                action_name="Apply for Leave",
                link="https://ascent.demo-company.com/leave-management/apply",
                steps=[
                    "Login to Ascent Portal",
                    "Go to 'Leave Management' Module",
                    "Select 'Leave Application'",
                    "Click on 'New Request'"
                ],
                keywords=[
                    "apply leave", "request leave", "take leave", "book leave",
                    "submit leave", "leave application", "new leave", "leave request"
                ],
                source="Master Actions Fallback"
            ),
            ActionGuide(
                action_name="Apply for Half-Day Leave",
                link="https://ascent.demo-company.com/leave-management/apply",
                steps=[
                    "Login to Ascent Portal",
                    "Go to 'Leave Management' Module",
                    "Select 'Leave Application'",
                    "Click on 'New Request'"
                ],
                keywords=[
                    "half day", "half-day", "partial leave", "half day leave",
                    "apply half day", "request half day"
                ],
                source="Master Actions Fallback"
            ),
            # Timesheet Queries
            ActionGuide(
                action_name="Raise OD/Attendance Regularisation",
                link="https://ascent.demo-company.com/attendance/od-application",
                steps=[
                    "Login to Ascent Portal",
                    "Go to Attendance",
                    "Select 'OD Application'"
                ],
                keywords=[
                    "od", "attendance regularisation", "regularization", "raise od",
                    "od application", "outdoor duty", "attendance correction"
                ],
                source="Master Actions Fallback"
            ),
            ActionGuide(
                action_name="Regularise Attendance for Missing Punches",
                link="https://ascent.demo-company.com/attendance/regularisation",
                steps=[
                    "Login to Ascent Portal",
                    "Go to Attendance",
                    "Select 'My Attendance Regularisation'"
                ],
                keywords=[
                    "missing punch", "regularise attendance", "attendance regularisation",
                    "forgot punch", "punch correction", "attendance correction", "regularize"
                ],
                source="Master Actions Fallback"
            ),
            ActionGuide(
                action_name="Update Timesheet",
                link="https://ascent.demo-company.com/timesheet",
                steps=[
                    "Login to Ascent Portal",
                    "Go to 'Timesheet' tab",
                    "Select 'Missing Timesheet'",
                    "Add Task",
                    "Submit"
                ],
                keywords=[
                    "timesheet", "update timesheet", "fill timesheet", "submit timesheet",
                    "missing timesheet", "add task", "timesheet entry"
                ],
                source="Master Actions Fallback"
            ),
            # Generic Queries
            ActionGuide(
                action_name="View Holiday Calendar",
                link="https://sap.demo-company.com/home/holiday-calendar",
                steps=[
                    "Login to SAP Portal",
                    "Go to Home Page",
                    "Scroll to the end of the page",
                    "Click on 'Holiday Calendar'"
                ],
                keywords=[
                    "holiday calendar", "holidays", "public holidays", "company holidays",
                    "view holidays", "holiday list", "calendar", "holiday"
                ],
                source="Master Actions Fallback"
            ),
            ActionGuide(
                action_name="Access HR Policies of the Organization",
                link="https://sap.demo-company.com/home/policies",
                steps=[
                    "Login to SAP Portal",
                    "Go to Home Page",
                    "Scroll to the end of the page",
                    "Click on 'Policies'"
                ],
                keywords=[
                    "hr policies", "policies", "company policies", "organization policies",
                    "access policies", "policy documents", "hr rules"
                ],
                source="Master Actions Fallback"
            ),
            ActionGuide(
                action_name="Find Learning Assignments",
                link="https://sap.demo-company.com/home/learning",
                steps=[
                    "Login to SAP Portal",
                    "Click on Home Dropdown",
                    "Click on 'Learning'"
                ],
                keywords=[
                    "learning", "learning assignments", "training", "courses",
                    "find learning", "my learning", "assignments"
                ],
                source="Master Actions Fallback"
            ),
            ActionGuide(
                action_name="Refer for Any Position",
                link="https://sap.demo-company.com/careers/referral",
                steps=[
                    "Login to SAP Portal",
                    "Click on 'Careers'",
                    "Go to 'Referral Tracking'",
                    "Add Referral & Submit"
                ],
                keywords=[
                    "referral", "refer", "refer position", "employee referral",
                    "referral tracking", "add referral", "job referral"
                ],
                source="Master Actions Fallback"
            ),
            ActionGuide(
                action_name="Raise Resignation in the Tool",
                link="https://sap.demo-company.com/profile/separation",
                steps=[
                    "Login to SAP Portal",
                    "Go to 'View My Profile'",
                    "Select 'Actions'",
                    "Click on 'Separation'"
                ],
                keywords=[
                    "resignation", "resign", "quit", "separation", "raise resignation",
                    "submit resignation", "leave company"
                ],
                source="Master Actions Fallback"
            ),
            # Payroll Queries
            ActionGuide(
                action_name="Access Payslips",
                link="https://ascent.demo-company.com/payroll/payslips",
                steps=[
                    "Login to Ascent Portal",
                    "Click on Menu",
                    "Select 'Payslips'"
                ],
                keywords=[
                    "payslip", "payslips", "salary slip", "access payslip",
                    "download payslip", "view payslip", "pay statement"
                ],
                source="Master Actions Fallback"
            ),
            ActionGuide(
                action_name="Declare Flexi Basket Components",
                link="https://ascent.demo-company.com/payroll/flexi-basket",
                steps=[
                    "Login to Ascent Portal",
                    "Click on Menu",
                    "Select 'Flexi Basket Declaration'"
                ],
                keywords=[
                    "flexi basket", "declare flexi", "flexi components", "flexi declaration",
                    "basket declaration", "salary components"
                ],
                source="Master Actions Fallback"
            ),
            ActionGuide(
                action_name="Submit Flexi Basket Bills",
                link="https://ascent.demo-company.com/payroll/manage-claims",
                steps=[
                    "Login to Ascent Portal",
                    "Click on Menu",
                    "Select 'Manage Claims'",
                    "Click 'New Request'"
                ],
                keywords=[
                    "flexi bills", "submit bills", "flexi basket bills", "claims",
                    "manage claims", "bill submission", "reimbursement",
                    "expense claim", "claim expenses", "travel claim", "lunch claim",
                    "meal claim", "client lunch", "client meal", "expense reimbursement",
                    "travel expenses", "claim travel", "expense", "expenses",
                    "claim reimbursement", "submit claim", "submit expense"
                ],
                source="Master Actions Fallback"
            ),
            ActionGuide(
                action_name="Update Bank Account for Salary Credit",
                link="https://ascent.demo-company.com/profile/personal-details",
                steps=[
                    "Login to Ascent Portal",
                    "Click on Menu",
                    "Select 'Personal Details'"
                ],
                keywords=[
                    "bank account", "update bank", "salary credit", "bank details",
                    "change bank", "account details", "salary account"
                ],
                source="Master Actions Fallback"
            ),
            ActionGuide(
                action_name="Declare Income Tax and View Tax Calculator",
                link="https://ascent.demo-company.com/payroll/tax-declaration",
                steps=[
                    "Login to Ascent Portal",
                    "Go to Main Menu",
                    "Select 'Investment Declaration/Income Tax Calculator'"
                ],
                keywords=[
                    "income tax", "tax declaration", "tax calculator", "declare tax",
                    "investment declaration", "tax", "it declaration"
                ],
                source="Master Actions Fallback"
            ),
            ActionGuide(
                action_name="View or Download Form-16",
                link="https://ascent.demo-company.com/payroll/form16",
                steps=[
                    "Login to Ascent Portal",
                    "Go to Main Menu",
                    "Click on 'Form-16'"
                ],
                keywords=[
                    "form 16", "form-16", "form16", "tax form", "download form 16",
                    "view form 16", "tax certificate"
                ],
                source="Master Actions Fallback"
            ),
            # PMS Queries
            ActionGuide(
                action_name="Update Goals",
                link="https://sap.demo-company.com/performance/goals",
                steps=[
                    "Login to SAP Portal",
                    "Go to Home Page",
                    "Under 'For You Today' click on 'Goal Setting by Employee' or go to Home Dropdown → Performance Inbox"
                ],
                keywords=[
                    "goals", "update goals", "goal setting", "set goals",
                    "performance goals", "objectives", "kpi"
                ],
                source="Master Actions Fallback"
            ),
            ActionGuide(
                action_name="Access Probation Dashboard",
                link="https://sap.demo-company.com/performance/probation",
                steps=[
                    "Login to SAP Portal",
                    "Go to Home Page",
                    "Under 'For You Today' click on 'Probation Icon' or go to Home Dropdown → Performance → Inbox"
                ],
                keywords=[
                    "probation", "probation dashboard", "probation review",
                    "access probation", "probation status"
                ],
                source="Master Actions Fallback"
            )
        ]
    
    def search_actions(self, query: str) -> List[ActionGuide]:
        """
        Search for relevant actions based on query keywords with intelligent relevance filtering
        Uses semantic keyword matching with multi-word phrase detection
        """
        query_lower = query.lower().strip()
        # Treat pure policy questions (no action verbs) as non-procedural
        if "policy" in query_lower:
            procedural_markers = {
                "how", "apply", "download", "update", "enroll", "enrol",
                "submit", "request", "file", "check", "view", "access",
                "complete", "fill", "log"
            }
            if not any(marker in query_lower for marker in procedural_markers):
                return []
        query_tokens = set(re.findall(r'\b\w+\b', query_lower))
        
        # Common stop words that shouldn't contribute to matching
        stop_words = {
            'a', 'an', 'the', 'is', 'are', 'was', 'were', 'be', 'been', 'being',
            'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'should',
            'could', 'may', 'might', 'can', 'i', 'you', 'me', 'my', 'to', 'for',
            'of', 'in', 'on', 'at', 'from', 'with', 'about', 'by', 'how', 'what',
            'where', 'when', 'why', 'who', 'which'
        }
        
        # Remove stop words for better matching
        meaningful_tokens = query_tokens - stop_words
        
        # If no meaningful tokens remain, return empty (too vague)
        if not meaningful_tokens:
            return []
        
        matches = []
        for action in self.actions:
            # Calculate match score based on keyword overlap
            score = 0
            matched_keywords = []
            
            for keyword in action.keywords:
                keyword_tokens = set(re.findall(r'\b\w+\b', keyword.lower())) - stop_words
                
                # Check for multi-word phrase match (higher weight)
                if keyword in query_lower:
                    score += len(keyword.split()) * 3  # 3 points per word in exact phrase
                    matched_keywords.append(keyword)
                else:
                    # Token overlap (lower weight)
                    overlap = len(meaningful_tokens & keyword_tokens)
                    if overlap > 0:
                        # Calculate relevance ratio: overlap / keyword_length
                        relevance_ratio = overlap / max(len(keyword_tokens), 1)
                        # Only count if at least 50% of keyword tokens match
                        if relevance_ratio >= 0.5:
                            score += overlap
                            matched_keywords.append(keyword)
            
            # Apply minimum threshold: require at least one meaningful match
            if score > 0 and matched_keywords:
                matches.append((score, action, matched_keywords))
        
        # Sort by score (descending)
        matches.sort(key=lambda x: x[0], reverse=True)
        
        # Apply intelligent filtering: remove low-confidence matches
        if matches:
            best_score = matches[0][0]
            # Only return matches within 40% of best score AND with at least 50% keyword relevance
            filtered_matches = [
                action for score, action, keywords in matches 
                if score >= best_score * 0.4 and score >= 2  # Require minimum score of 2 for relevance
            ]
            return filtered_matches
        
        return []


class MasterActionsToolInput(BaseModel):
    """Input schema for Master Actions Tool"""
    query: str = Field(
        ...,
        description="The query about HOW TO perform an action (e.g., 'how to apply leave', 'download payslip')"
    )


class MasterActionsTool(BaseTool):
    """
    Master Actions Tool - Provides step-by-step procedural guidance with links
    
    Use this tool when users ask HOW TO perform specific actions like:
    - Applying for leave
    - Downloading payslips
    - Updating personal details
    - Enrolling in training
    - Checking leave balance
    
    This tool returns direct links and step-by-step instructions.
    """
    
    name: str = "master_actions_guide"
    description: str = (
        "Provides step-by-step instructions with direct links for performing HR system actions. "
        "Use this tool when the user asks HOW TO do something specific OR when they request "
        "links/access to HR portals and resources. Examples: "
        "'how to apply leave', 'download payslip', 'update profile', 'enroll in training', "
        "'check leave balance', 'holiday calendar', 'view policies', 'access learning portal', "
        "'show me form-16', 'where can I find payslips'. "
        "ALWAYS use this tool for queries about accessing/viewing/downloading HR documents or portals. "
        "Returns actionable links and clear step-by-step procedures."
    )
    args_schema: type[BaseModel] = MasterActionsToolInput
    
    database: MasterActionsDatabase = Field(default=None, exclude=True)
    
    def __init__(self, cache_dir: Optional[str] = None, **kwargs):
        """
        Initialize MasterActionsTool with optional cache directory
        
        Args:
            cache_dir: Directory containing cached S3 documents (e.g., /tmp/hr_bot_s3_cache/employee/)
        """
        database_instance = MasterActionsDatabase(cache_dir=cache_dir)
        kwargs['database'] = database_instance
        super().__init__(**kwargs)
        
        # Initialize _last_sources
        object.__setattr__(self, '_last_sources', [])
    
    def _run(self, query: str) -> str:
        """
        Execute search for procedural actions
        
        Args:
            query: User's query about HOW TO perform an action
            
        Returns:
            Formatted string with links and steps, or "NO_ACTION_FOUND"
        """
        try:
            # Reset last sources for this invocation to avoid leaking previous runs
            object.__setattr__(self, '_last_sources', [])
            
            # Search for matching actions
            matching_actions = self.database.search_actions(query)
            
            if not matching_actions:
                return "NO_ACTION_FOUND"
            
            # Format output
            output = f"Found {len(matching_actions)} relevant action(s):\n\n"
            
            sources: Dict[str, List[str]] = {}
            for idx, action in enumerate(matching_actions, 1):
                output += f"**{idx}. {action.action_name}**\n"
                if action.link:
                    output += f"🔗 Link: {action.link}\n\n"
                else:
                    output += "🔗 Link: Not provided. Follow the steps below.\n\n"
                output += "**Steps:**\n"
                for step_num, step in enumerate(action.steps, 1):
                    output += f"   {step_num}. {step}\n"
                output += "\n"
                
                source_key = action.source or "Master Actions Guide"
                sources.setdefault(source_key, []).append(action.action_name)
            
            # Store sources in "Document → action names" format to avoid randomness
            formatted_sources: List[str] = []
            for doc_name, action_names in sources.items():
                joined_actions = "; ".join(action_names)
                formatted_sources.append(f"{doc_name}: {joined_actions}")
            object.__setattr__(self, '_last_sources', formatted_sources)
            output += "Sources: " + " | ".join(formatted_sources) + "\n"
            
            return output
            
        except Exception as e:
            return f"Error searching actions: {str(e)}"
    
    def last_sources(self) -> List[str]:
        """Return the most recent set of sources emitted by the tool."""
        try:
            return list(object.__getattribute__(self, '_last_sources'))
        except AttributeError:
            return []

    def clear_last_sources(self) -> None:
        """Explicitly clear cached source metadata."""
        object.__setattr__(self, '_last_sources', [])
