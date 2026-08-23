document.addEventListener("DOMContentLoaded", () => {
    const chatForm = document.getElementById("chat-form");
    const userInput = document.getElementById("user-input");
    const chatMessages = document.getElementById("chat-messages");
    const welcomeScreen = document.getElementById("welcome-screen");
    const newChatBtn = document.getElementById("new-chat-btn");
    const sendBtn = document.getElementById("send-btn");

    // Maintain chat history state
    let chatHistory = [];

    // Configure marked options (e.g. open links in new tab)
    const renderer = new marked.Renderer();
    renderer.link = function(href, title, text) {
        return `<a href="${href}" target="_blank" rel="noopener noreferrer">${text}</a>`;
    };
    marked.setOptions({ renderer: renderer });

    // Focus input on load
    userInput.focus();

    // Auto-resize textarea as user types
    userInput.addEventListener("input", function() {
        this.style.height = "auto";
        this.style.height = (this.scrollHeight - 4) + "px";
    });

    // Handle Enter key submit, Shift+Enter for newline
    userInput.addEventListener("keydown", (e) => {
        if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            chatForm.dispatchEvent(new Event("submit"));
        }
    });

    // Clear chat and return to welcome screen
    newChatBtn.addEventListener("click", () => {
        chatHistory = []; // Reset conversational history
        chatMessages.innerHTML = "";
        chatMessages.appendChild(welcomeScreen);
        welcomeScreen.style.display = "flex";
        userInput.value = "";
        userInput.style.height = "auto";
        userInput.focus();
    });

    // Submit form action
    chatForm.addEventListener("submit", async (e) => {
        e.preventDefault();

        const messageText = userInput.value.trim();
        if (!messageText) return;

        // Reset input box height
        userInput.value = "";
        userInput.style.height = "auto";

        // Hide welcome screen if visible
        if (welcomeScreen.style.display !== "none") {
            welcomeScreen.style.display = "none";
        }

        // Add user message to chat
        appendMessage("user", messageText);

        // Add loading message
        const loadingId = appendLoadingMessage();

        try {
            // Disable send button during fetch
            setFormState(true);

            // Send the last 6 messages (3 turns) as history to keep payloads lightweight
            const historyToSend = chatHistory.slice(-6);

            const response = await fetch("/api/chat", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json"
                },
                body: JSON.stringify({ 
                    message: messageText,
                    history: historyToSend
                })
            });

            if (!response.ok) {
                throw new Error(`Server returned status ${response.status}`);
            }

            const data = await response.json();
            
            // Remove loading message and replace with answer
            removeMessage(loadingId);
            appendMessage("bot", data.answer, data.citations);

            // Record this turn in the conversation state
            chatHistory.push({ role: "user", content: messageText });
            chatHistory.push({ role: "bot", content: data.answer });

        } catch (error) {
            console.error("Error sending message:", error);
            removeMessage(loadingId);
            appendMessage("bot", "❌ Sorry, I encountered an error communicating with the server. Please verify the backend is running and try again.");
        } finally {
            setFormState(false);
            userInput.focus();
        }
    });

    // Helper to toggle submit state
    function setFormState(disabled) {
        userInput.disabled = disabled;
        sendBtn.disabled = disabled;
    }

    // Function to append standard message bubbles
    function appendMessage(sender, text, citations = []) {
        const wrapper = document.createElement("div");
        wrapper.className = `message-wrapper ${sender}`;

        const container = document.createElement("div");
        container.className = "message-container";

        const avatar = document.createElement("div");
        avatar.className = "avatar";
        avatar.textContent = sender === "user" ? "U" : "W";

        const body = document.createElement("div");
        body.className = "message-body";
        
        if (sender === "user") {
            body.textContent = text;
        } else {
            // Render markdown using Marked.js safely
            body.innerHTML = marked.parse(text);

            // Append citations if they exist
            if (citations && citations.length > 0) {
                const citationsSection = document.createElement("div");
                citationsSection.className = "citations-container";

                const header = document.createElement("div");
                header.className = "citations-header";
                header.innerHTML = `
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"></path><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"></path></svg>
                    Sources:
                `;
                citationsSection.appendChild(header);

                const list = document.createElement("div");
                list.className = "citations-list";

                citations.forEach((citation) => {
                    const [title, url] = citation.split("|");
                    if (title) {
                        const badge = document.createElement("a");
                        badge.className = "citation-badge";
                        badge.textContent = title;
                        badge.href = url || "#";
                        badge.target = "_blank";
                        badge.rel = "noopener noreferrer";
                        list.appendChild(badge);
                    }
                });

                citationsSection.appendChild(list);
                body.appendChild(citationsSection);
            }
        }

        container.appendChild(avatar);
        container.appendChild(body);
        wrapper.appendChild(container);
        chatMessages.appendChild(wrapper);

        scrollToBottom();
    }

    // Function to append a loading indicator message
    function appendLoadingMessage() {
        const id = "loading-" + Date.now();
        
        const wrapper = document.createElement("div");
        wrapper.className = "message-wrapper bot";
        wrapper.id = id;

        const container = document.createElement("div");
        container.className = "message-container";

        const avatar = document.createElement("div");
        avatar.className = "avatar";
        avatar.textContent = "W";

        const body = document.createElement("div");
        body.className = "message-body loading-message";
        body.innerHTML = `
            Searching Wikipedia and generating response
            <div class="bouncing-loader">
                <div></div>
                <div></div>
                <div></div>
            </div>
        `;

        container.appendChild(avatar);
        container.appendChild(body);
        wrapper.appendChild(container);
        chatMessages.appendChild(wrapper);

        scrollToBottom();
        return id;
    }

    // Function to remove a message by ID
    function removeMessage(id) {
        const element = document.getElementById(id);
        if (element) {
            element.remove();
        }
    }

    // Keep chat container scrolled to the bottom
    function scrollToBottom() {
        chatMessages.scrollTop = chatMessages.scrollHeight;
    }

    // Expose suggestion helper to window scope for onclick in HTML
    window.useSuggestion = function(text) {
        userInput.value = text;
        userInput.style.height = "auto";
        userInput.style.height = (userInput.scrollHeight - 4) + "px";
        userInput.focus();
    };
});
