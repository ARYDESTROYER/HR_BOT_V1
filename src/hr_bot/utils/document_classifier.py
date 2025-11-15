"""
Document Classification System for HR Bot
Categorizes documents into types for improved retrieval with larger document sets
"""
import re
from typing import List, Dict, Optional, Set
from pathlib import Path
from dataclasses import dataclass
from enum import Enum


class DocumentCategory(Enum):
    """Document categories for HR policies"""
    LEAVE = "leave"
    BENEFITS = "benefits"
    CONDUCT = "conduct"
    COMPENSATION = "compensation"
    WORKING_CONDITIONS = "working_conditions"
    TERMINATION = "termination"
    DATA_PROTECTION = "data_protection"
    RECRUITMENT = "recruitment"
    EXECUTIVE = "executive"
    GENERAL = "general"


@dataclass
class DocumentMetadata:
    """Enhanced metadata for documents with classification"""
    source: str
    file_path: str
    category: DocumentCategory
    tags: Set[str]
    priority: int  # 1=high, 2=medium, 3=low
    access_level: str  # "executive", "employee", "all"
    keywords: Set[str]


class DocumentClassifier:
    """
    Classifies HR documents into categories and extracts metadata
    Improves retrieval by enabling category-based filtering
    """
    
    def __init__(self):
        """Initialize the classifier with keyword patterns"""
        # Define category keywords
        self.category_keywords = {
            DocumentCategory.LEAVE: {
                "leave", "holiday", "vacation", "sick", "absence", "maternity", 
                "paternity", "parental", "time off", "absence", "sickness"
            },
            DocumentCategory.BENEFITS: {
                "benefit", "reimbursement", "allowance", "perks", "insurance",
                "pension", "retirement", "health", "wellness"
            },
            DocumentCategory.CONDUCT: {
                "policy", "conduct", "harassment", "ethics", "disciplinary", 
                "behavior", "code", "compliance", "whistleblowing"
            },
            DocumentCategory.COMPENSATION: {
                "salary", "pay", "compensation", "bonus", "remuneration", 
                "reward", "incentive", "car rental", "budget"
            },
            DocumentCategory.WORKING_CONDITIONS: {
                "working", "work", "home", "remote", "flexible", "office", 
                "hours", "equipment", "byod", "device", "communication"
            },
            DocumentCategory.TERMINATION: {
                "termination", "redundancy", "resignation", "exit", "dismissal",
                "garden leave", "notice", "separation"
            },
            DocumentCategory.DATA_PROTECTION: {
                "data", "protection", "privacy", "gdpr", "personal information",
                "confidential", "security"
            },
            DocumentCategory.RECRUITMENT: {
                "recruitment", "hiring", "interview", "onboarding", "induction",
                "probation", "appointment"
            },
            DocumentCategory.EXECUTIVE: {
                "executive", "leadership", "calibration", "performance review",
                "workforce planning", "cxo", "budget", "strategy"
            }
        }
        
        # Define priority keywords
        self.priority_keywords = {
            1: {"policy", "mandatory", "required", "compliance", "critical"},
            2: {"guideline", "procedure", "process", "standard"},
            3: {"form", "template", "example", "reference"}
        }
        
        # Define access level patterns
        self.executive_patterns = {
            "executive", "leadership", "cxo", "calibration", "performance review",
            "compensation", "bonus", "budget", "workforce planning"
        }
    
    def classify_document(self, file_path: str, content: str) -> DocumentMetadata:
        """
        Classify a document and extract metadata
        
        Args:
            file_path: Path to the document file
            content: Text content of the document
            
        Returns:
            DocumentMetadata object with classification and tags
        """
        file_name = Path(file_path).name.lower()
        content_lower = content.lower()
        
        # Determine category
        category = self._determine_category(file_name, content_lower)
        
        # Extract tags
        tags = self._extract_tags(file_name, content_lower, category)
        
        # Determine priority
        priority = self._determine_priority(file_name, content_lower)
        
        # Determine access level
        access_level = self._determine_access_level(file_name, content_lower)
        
        # Extract keywords
        keywords = self._extract_keywords(content_lower)
        
        return DocumentMetadata(
            source=Path(file_path).name,
            file_path=file_path,
            category=category,
            tags=tags,
            priority=priority,
            access_level=access_level,
            keywords=keywords
        )
    
    def _determine_category(self, file_name: str, content: str) -> DocumentCategory:
        """Determine the primary category of a document"""
        category_scores = {}
        
        # Score each category based on keyword matches
        for category, keywords in self.category_keywords.items():
            score = 0
            # Check filename (higher weight)
            for keyword in keywords:
                if keyword in file_name:
                    score += 3
                if keyword in content:
                    score += 1
            category_scores[category] = score
        
        # Return category with highest score
        if max(category_scores.values()) == 0:
            return DocumentCategory.GENERAL
        
        return max(category_scores, key=category_scores.get)
    
    def _extract_tags(self, file_name: str, content: str, category: DocumentCategory) -> Set[str]:
        """Extract relevant tags from document"""
        tags = set()
        
        # Add category as a tag
        tags.add(category.value)
        
        # Add specific tags based on content
        if "annual" in content or "yearly" in content:
            tags.add("annual")
        if "form" in file_name or "template" in file_name:
            tags.add("form")
        if "policy" in file_name or "policy" in content:
            tags.add("policy")
        if "guideline" in content:
            tags.add("guideline")
        if "procedure" in content:
            tags.add("procedure")
        
        # Add specific HR-related tags
        if "csp" in content or "company sick pay" in content:
            tags.add("csp")
        if "notification" in content:
            tags.add("notification")
        if "certification" in content:
            tags.add("certification")
        
        return tags
    
    def _determine_priority(self, file_name: str, content: str) -> int:
        """Determine document priority (1=high, 2=medium, 3=low)"""
        for priority, keywords in self.priority_keywords.items():
            for keyword in keywords:
                if keyword in file_name or keyword in content:
                    return priority
        return 2  # Default to medium priority
    
    def _determine_access_level(self, file_name: str, content: str) -> str:
        """Determine access level for the document"""
        if any(pattern in file_name or pattern in content for pattern in self.executive_patterns):
            return "executive"
        elif "executive-only" in file_name or "executive only" in content:
            return "executive"
        else:
            return "employee"
    
    def _extract_keywords(self, content: str) -> Set[str]:
        """Extract important keywords from content"""
        # Simple keyword extraction - could be enhanced with NLP
        hr_keywords = {
            "employee", "employer", "company", "policy", "procedure", "guideline",
            "requirement", "obligation", "right", "responsibility", "manager",
            "hr", "human resources", "department", "staff", "personnel"
        }
        
        found_keywords = set()
        for keyword in hr_keywords:
            if keyword in content:
                found_keywords.add(keyword)
        
        return found_keywords
    
    def get_category_filter_terms(self, category: DocumentCategory) -> List[str]:
        """Get search terms for filtering by category"""
        if category in self.category_keywords:
            return list(self.category_keywords[category])
        return []