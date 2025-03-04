from typing import Dict, List, Optional, Any, Literal, Union
from langchain_openai import ChatOpenAI
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import START, MessagesState, StateGraph, END
from langgraph.prebuilt import ToolNode

from src.tools.rag_tools import RAGTools
from src.core.vector_store import VectorStore
from src.core.workflow import RAGWorkflow
from src.tools.image_tools import ImageTools
import re
# Create LangChain agent
from langchain.agents import AgentExecutor, create_openai_tools_agent
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from src.tools import RAGTools


class WebRAGSystem:
    def __init__(self, openai_api_key: str):
        self.openai_api_key = openai_api_key
        
        # Initialize core components
        self.rag_tools = RAGTools()
        self.vector_store = VectorStore(openai_api_key)
        self.conversation_history = {}  # Initialize conversation history
        
        # Initialize LLM with vision capabilities
        self.llm = ChatOpenAI(
            temperature=0.1,
            openai_api_key=openai_api_key,
            model="gpt-4o-mini"  # Changed to GPT-4o for better multimodal capabilities
        )
        
        # Initialize workflow
        self.workflow = StateGraph(state_schema=MessagesState)
        self.workflow.add_node("rag_node", self._process_rag_query)
        self.workflow.add_edge(START, "rag_node")
        
        # Set default mode
        self.mode = 'explore'
        
        # Initialize tools
        self.tools = self._connect_llm_tools()
        
        # Initialize memory
        self.memory = MemorySaver()
        # Compile without recursion_limit (we'll handle that differently)
        self.app = self.workflow.compile(checkpointer=self.memory)
        
        # Track recursion to prevent infinite loops
        self.recursion_count = 0
        self.max_recursion = 20
        
    def _connect_llm_tools(self):
        """Initialize tools for the LLM"""
        toolchain = self.rag_tools.get_tools()
        self.llm = self.llm.bind_tools(toolchain)
        
        # Set up tool node
        tools = ToolNode(toolchain)
        self.workflow.add_node('tools', tools)
        
        def branch(state: MessagesState) -> Literal['tools', '__end__']:
            latest = state['messages'][-1]
            return 'tools' if hasattr(latest, 'tool_calls') and len(latest.tool_calls) > 0 else END
            
        self.workflow.add_conditional_edges('rag_node', branch)
        self.workflow.add_edge('tools', 'rag_node')
        
        return {tool.name: tool for tool in toolchain}
        
    def _process_rag_query(self, state: MessagesState) -> Dict:
        try:
            current_messages = state.get("messages", [])
            if not current_messages:
                return {"messages": [AIMessage(content="No message received.")]}
                
            # Extract conversation history and create system prompt
            conversation_history = RAGWorkflow.process_messages(current_messages)
            latest_message = current_messages[-1]
            
            # Check if the latest message contains image context
            image_content = []
            if hasattr(latest_message, 'additional_kwargs') and 'image_content' in latest_message.additional_kwargs:
                image_content = latest_message.additional_kwargs['image_content']
                
            system_prompt = RAGWorkflow.create_system_prompt(
                latest_message, 
                conversation_history,
                image_content=image_content
            )
            
            # Create message list with any image content
            messages = [SystemMessage(content=system_prompt)]
            
            # Add all messages, ensuring any with image content are properly formatted
            for msg in current_messages:
                if hasattr(msg, 'additional_kwargs') and 'image_content' in msg.additional_kwargs:
                    # This message contains image data
                    images = msg.additional_kwargs['image_content']
                    # Create a new message with correct format for vision model
                    content = []
                    
                    # Add text content
                    if hasattr(msg, 'content') and msg.content:
                        content.append({"type": "text", "text": msg.content})
                    
                    # Add image content
                    for img in images:
                        content.append({
                            "type": "image_url",
                            "image_url": {"url": img}
                        })
                    
                    # Replace with properly formatted message for vision model
                    if isinstance(msg, HumanMessage):
                        messages.append(HumanMessage(content=content))
                    else:
                        messages.append(msg)
                else:
                    # Regular message without images
                    messages.append(msg)
            
            # Get response from the LLM
            response = self.llm.invoke(messages)
            
            return {"messages": current_messages + [response]}
            
        except Exception as e:
            print(f"Error in RAG processing: {str(e)}")
            return {"messages": current_messages + [AIMessage(content=f"An error occurred while processing your question: {str(e)}")]}
        
    def _extract_phone_number_from_history(self, thread_id: str) -> Optional[str]:
        """Extract phone number from conversation history"""
        if thread_id not in self.conversation_history:
            return None
        
        # Look for phone numbers in history
        phone_pattern = r'(\+?[\d\s\-\(\)]{10,})'
        
        for msg in self.conversation_history[thread_id]:
            if hasattr(msg, 'content') and isinstance(msg.content, str):
                matches = re.findall(phone_pattern, msg.content)
                if matches:
                    # Return the last matched phone number
                    return matches[-1].strip()
        
        return None

    def _extract_message_content(self, query: str) -> Optional[str]:
        """Extract message content from query"""
        # Look for quotes or patterns like "say X" or "saying X"
        
        # Try to find content in quotes
        quote_pattern = r'"([^"]*)"'
        quote_matches = re.findall(quote_pattern, query)
        if quote_matches:
            return quote_matches[0]
        
        # Try to find content after "say" or "saying"
        say_pattern = r'say(?:ing)?\s+(.+?)(?:$|\s+to\s+)'
        say_matches = re.findall(say_pattern, query.lower())
        if say_matches:
            return say_matches[0]
        
        # If we can't extract a specific message, return a default
        return "Hello!"
        
    def generate_image_directly(self, prompt: str) -> str:
        """
        Generate an image directly without sending the full conversation context to OpenAI.
        This avoids token limit errors when generating images.
        
        Args:
            prompt: The image description to generate
            
        Returns:
            The response with the image data
        """
        try:
            # Create an instance of ImageTools to directly generate the image
            image_tools = ImageTools()
            
            # Generate the image
            image_data, error = image_tools.generate_image(prompt)
            
            if error:
                return f"Error generating image: {error}"
            
            # Return the markdown image syntax for direct rendering
            return f"I've created an image of {prompt}:\n\n![Generated Image]({image_data})"
        except Exception as e:
            return f"Error generating image: {str(e)}"
    
    def get_answer(self, query: str, thread_id: str = None, mode: str = "explore", 
                  project_context: dict = None, image_context: str = None,
                  attached_images: list = None) -> str:
        """
        Get answer from the RAG system for a user query.
        
        Args:
            query: User question
            thread_id: Optional thread ID for conversation continuity
            mode: Mode for the RAG system (explore, setup, etc.)
            project_context: Optional project context information
            image_context: Optional context from analyzed images
            attached_images: Optional list of attached image data
            
        Returns:
            Response from the system
        """
        try:
            # Check if this is a direct image generation request
            image_request_pattern = r"(generate|create|make|draw) .*image of"
            
            if re.search(image_request_pattern, query.lower()):
                # Extract the image description
                description_start = query.lower().find("image of") + 8
                if description_start > 8:  # Found "image of"
                    image_description = query[description_start:].strip()
                    # If the description ends with punctuation, remove it
                    image_description = re.sub(r'[.!?]$', '', image_description)
                    
                    if image_description:
                        # Call the direct image generation method
                        return self.generate_image_directly(image_description)
            
            # Special handling for SMS requests
            sms_pattern = r"(send|text|sms) .*(message|sms|text)"
            if re.search(sms_pattern, query.lower()):
                # Extract phone number and message
                phone_number = None
                message = None
                
                # Try to extract phone number from query
                phone_pattern = r'(\+?[\d\s\-\(\)]{10,})'
                phone_matches = re.findall(phone_pattern, query)
                if phone_matches:
                    phone_number = phone_matches[0].strip()
                else:
                    # Try to find phone number in conversation history
                    phone_number = self._extract_phone_number_from_history(thread_id)
                
                # Extract message content
                message = self._extract_message_content(query)
                
                if phone_number and message:
                    # Get SMS tool
                    rag_tools = RAGTools()
                    tools = rag_tools.get_tools()
                    for tool in tools:
                        if tool.name == "send_sms":
                            result = tool.invoke({"recipient": phone_number, "message": message})
                            
                            # Add to conversation history
                            if thread_id not in self.conversation_history:
                                self.conversation_history[thread_id] = []
                            self.conversation_history[thread_id].append(HumanMessage(content=query))
                            self.conversation_history[thread_id].append(AIMessage(
                                content=f"✅ SMS sent to {phone_number} with message: '{message}'. {result}"
                            ))
                            
                            return f"✅ SMS sent to {phone_number} with message: '{message}'. {result}"
            
            # Special handling for call requests
            call_pattern = r"(call|phone|ring) .*"
            if re.search(call_pattern, query.lower()):
                # Extract phone number and message
                phone_number = None
                message = None
                
                # Try to extract phone number from query
                phone_pattern = r'(\+?[\d\s\-\(\)]{10,})'
                phone_matches = re.findall(phone_pattern, query)
                if phone_matches:
                    phone_number = phone_matches[0].strip()
                else:
                    # Try to find phone number in conversation history
                    phone_number = self._extract_phone_number_from_history(thread_id)
                
                # Extract message content
                message = self._extract_message_content(query)
                
                if phone_number:
                    # Get call tool
                    rag_tools = RAGTools()
                    tools = rag_tools.get_tools()
                    for tool in tools:
                        if tool.name == "make_call":
                            result = tool.invoke({"recipient": phone_number, "message": message})
                            
                            # Add to conversation history
                            if thread_id not in self.conversation_history:
                                self.conversation_history[thread_id] = []
                            self.conversation_history[thread_id].append(HumanMessage(content=query))
                            self.conversation_history[thread_id].append(AIMessage(
                                content=f"✅ Call initiated to {phone_number} with message: '{message}'. {result}"
                            ))
                            
                            return f"✅ Call initiated to {phone_number} with message: '{message}'. {result}"
            
            # Get or create history for this thread
            if thread_id not in self.conversation_history:
                self.conversation_history[thread_id] = []
            
            # Get conversation history
            messages = self.conversation_history[thread_id]
            
            # Process messages to get conversation context
            conversation_history = RAGWorkflow.process_messages(messages)
            
            # Get the latest message or create a new message object for the first message
            if messages:
                latest_message = messages[-1]
            else:
                # For the first message in a conversation, create a mock message with the current query
                latest_message = HumanMessage(content=query)

            # Create system prompt
            system_prompt = RAGWorkflow.create_system_prompt(
                latest_message=latest_message,
                conversation_history=conversation_history,
                image_content=attached_images
            )
            
            # Add explicit instructions for SMS and calling
            system_prompt += "\n\nIMPORTANT: When asked to send an SMS or make a call, use the appropriate tool (send_sms or make_call) directly. Do not hesitate to use these tools when explicitly requested."
            
            # Augment system prompt with project context if available
            if project_context:
                project_context_str = "\n\nProject Context:\n"
                for key, value in project_context.items():
                    project_context_str += f"{key}: {value}\n"
                system_prompt += project_context_str
            
            # Augment system prompt with image context if available
            if image_context:
                system_prompt += f"\n\nImage Context:\n{image_context}\n"
            
            # Add mode-specific instructions
            if mode == "setup":
                system_prompt += "\nYou are in SETUP mode. Focus on helping the user configure systems, services, or applications. Provide detailed step-by-step instructions. When appropriate, suggest best practices for configuration."
            elif mode == "explore":
                system_prompt += "\nYou are in EXPLORE mode. Focus on helping the user discover information and learn new things. Be comprehensive and educational in your responses."
            
            # Get tools
            rag_tools = RAGTools()
            tools = rag_tools.get_tools()

            # Initialize LLM with tools explicitly bound
            self.llm = ChatOpenAI(
                model="gpt-4o",
                temperature=0.7,
                openai_api_key=self.openai_api_key
            ).bind_tools(tools)  # Explicitly bind tools
            
            # Create prompt using tuple format instead of message objects to fix template issues
            prompt = ChatPromptTemplate.from_messages([
                ("system", system_prompt),
                MessagesPlaceholder(variable_name="chat_history"),
                ("human", "{input}"),  # Changed format to tuple
                MessagesPlaceholder(variable_name="agent_scratchpad")
            ])
            
            # Create agent
            agent = create_openai_tools_agent(self.llm, tools, prompt)
            
            # Create agent executor with return_intermediate_steps for better debugging
            agent_executor = AgentExecutor(
                agent=agent,
                tools=tools,
                verbose=True,
                handle_parsing_errors=True,
                max_iterations=5,
                return_intermediate_steps=True  # Add for better debugging
            )
            
            # Run agent to get response
            response = agent_executor.invoke({
                "input": query,
                "chat_history": messages
            })
            
            # Get output and intermediate steps for debugging if needed
            output = response.get("output", "I couldn't generate a response. Please try again.")
            steps = response.get("intermediate_steps", [])
            
            # Log steps for debugging if there's an issue
            if not output or "{input}" in output:
                print(f"DEBUG - Intermediate steps: {steps}")
                # Fallback response if template wasn't filled
                output = "I apologize for the error in processing your request. Could you please rephrase your question?"
            
            # Update conversation history
            self.conversation_history[thread_id].append(HumanMessage(content=query))
            self.conversation_history[thread_id].append(AIMessage(content=output))
            
            # Return response
            return output
            
        except Exception as e:
            import traceback
            error_message = f"Error processing query: {str(e)}\n{traceback.format_exc()}"
            print(error_message)
            return f"I encountered an error while processing your request: {str(e)}"