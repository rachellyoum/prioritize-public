// ==========================================
    // 1. CONFIG & AUTH HELPERS
    // ==========================================
    const API_URL = ""; 

    // Helper: Parse JWT to read dates
    function parseJwt(token) {
        try {
            return JSON.parse(atob(token.split('.')[1]));
        } catch (e) {
            return null;
        }
    }

    // check if jwt expired
    function getToken() {
        const t = localStorage.getItem('token');
        if (!t) return null;

        const payload = parseJwt(t);
        if (!payload || !payload.exp) return null;

        // Check if past this date
        if (Date.now() >= payload.exp * 1000) {
            console.warn("Token expired naturally. Removing.");
            logout();
            return null;
        }
        return t;
    }

    window.logout = function() {
        console.log("Logging out...");
        localStorage.removeItem('token');
        sessionStorage.clear();
        window.location.replace('login.html'); 
    };

    // Initialize User
    const token = getToken(); // This now auto-deletes if expired
    const userPayload = token ? parseJwt(token) : null;
    const currentUserId = userPayload ? parseInt(userPayload.sub) : null;

    if (!token || !currentUserId) {
        window.location.href = 'login.html';
    }

    // Helper: Authenticated Fetch
    async function authFetch(url, options = {}) {
        const validToken = getToken();
        if (!validToken) return;

        const headers = {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${validToken}`,
            ...options.headers
        };

        const response = await fetch(url, { ...options, headers });

        // remove token when 401
        if (response.status === 401) {
            console.warn("Session expired or invalid. Please log in.");
            logout();
        }
        return response;
    }

    // ==========================================
    // HELPER: LOCAL TIME STRING
    // ==========================================
    // Fixes the timezone display issue in Prompts
    function getLocalISOString() {
        const now = new Date();
        const offset = now.getTimezoneOffset() * 60000; // Offset in ms
        const localISOTime = new Date(now - offset).toISOString().slice(0, 16).replace('T', ' ');
        return localISOTime; // Returns "2025-12-04 12:30" (Local)
    }

    // ==========================================
    // 2. INITIALIZATION
    // ==========================================
    document.addEventListener('DOMContentLoaded', () => {
        loadTasks();
        loadFriendsList();
        loadFriendRequests();
        checkActiveSession();
        loadAvailability();
        loadSettings();
        logSystemEvent("session_start");
    });

    // ==========================================
    // 3. TASK MANAGEMENT
    // ==========================================
    const taskTableBody = document.querySelector("#taskTable tbody");

    async function loadTasks() {
        try {
            const res = await authFetch(`${API_URL}/api/tasks`);
            if(!res.ok) throw new Error("Failed to load tasks");
            const tasks = await res.json();
            renderTaskTable(tasks);
            updateTimerDropdown(tasks); // Sync timer dropdown
        } catch (e) {
            console.error(e);
        }
    }

    function renderTaskTable(tasks) {
        taskTableBody.innerHTML = "";
        tasks.forEach(task => {
            const row = taskTableBody.insertRow();
            row.dataset.id = task.id; // Store ID for edit/delete
            
            // Format Date
            const dateObj = new Date(task.deadline);
            const dateStr = dateObj.toLocaleDateString() + " " + dateObj.toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'});

            row.innerHTML = `
                <td><input type="checkbox" /></td>
                <td>${task.name}</td>
                <td>${dateStr}</td>
                <td>${task.weight_pct}%</td>
                <td>${task.difficulty}</td>
                <td>${task.estimated_hours ?? ""}</td>
            `;
        });
    }

    // --- Create Task ---
    document.getElementById("btn-create-task").addEventListener("click", async () => {
        const name = prompt("Task name:");
        if (!name) return;
        
        // Simple prompts for now (could be a modal in future)
        const defaultTime = getLocalISOString();
        const deadlineInput = prompt("Deadline (YYYY-MM-DD HH:MM):", defaultTime);
        const weight = prompt("Grade weight (%):", "10");
        const difficulty = prompt("Difficulty (easy/medium/hard):", "medium");
        const hours = prompt("Estimated Hours:", "2");

        if (!deadlineInput || !weight || !difficulty) return;

        try {
            // Convert Input string to ISO Date object (Browser handles locale)
            const deadlineDate = new Date(deadlineInput);

            const res = await authFetch(`${API_URL}/api/tasks`, {
                method: "POST",
                body: JSON.stringify({
                    name: name,
                    deadline: deadlineDate.toISOString(), // Send as UTC to backend
                    weight_pct: parseFloat(weight),
                    difficulty: difficulty.toLowerCase(),
                    estimated_hours: parseFloat(hours)
                })
            });
            
            if(res.ok) loadTasks();
            else alert("Error creating task: " + (await res.json()).detail);

        } catch(e) { alert(e.message); }
    });

    // --- Delete Task ---
    document.getElementById("btn-delete-task").addEventListener("click", async () => {
        const checkboxes = taskTableBody.querySelectorAll("input[type='checkbox']:checked");
        for (const cb of checkboxes) {
            const row = cb.closest("tr");
            const taskId = row.dataset.id;
            await authFetch(`${API_URL}/api/tasks/${taskId}`, { method: "DELETE" });
        }
        loadTasks();
    });

    // --- Edit Task ---
    document.getElementById("btn-edit-task").addEventListener("click", async () => {
        // Find selected checkbox
        const selectedCheckbox = taskTableBody.querySelector('input[type="checkbox"]:checked');
        if (!selectedCheckbox) {
            alert("Please select a task to edit.");
            return;
        }

        const row = selectedCheckbox.closest("tr");
        const taskId = row.dataset.id;

        try {
            // Load current task to prefill prompts
            const res = await authFetch(`${API_URL}/api/tasks`);
            if (!res.ok) throw new Error("Failed to load tasks");
            const tasks = await res.json();
            const task = tasks.find(t => t.id === taskId);
            if (!task) {
                alert("Task not found.");
                return;
            }

            const name = prompt("Task name:", task.name);
            if (!name) return;

            const dateObj = new Date(task.deadline);
            const offset = dateObj.getTimezoneOffset() * 60000;
            const localStr = new Date(dateObj - offset).toISOString().slice(0, 16).replace('T', ' ');

            const deadlineInput = prompt("Deadline (YYYY-MM-DD HH:MM):", localStr);
            const weight = prompt("Grade weight (%):", task.weight_pct);
            const difficulty = prompt("Difficulty (easy/medium/hard):", task.difficulty);
            const hours = prompt("Estimated Hours:", task.estimated_hours ?? 2);

            if (!deadlineInput || !weight || !difficulty) return;

            const patchBody = {
                name,
                deadline: new Date(deadlineInput).toISOString(),
                weight_pct: parseFloat(weight),
                difficulty: difficulty.toLowerCase(),
                estimated_hours: parseFloat(hours)
            };

            const patchRes = await authFetch(`${API_URL}/api/tasks/${taskId}`, {
                method: "PATCH",
                body: JSON.stringify(patchBody)
            });

            if (!patchRes.ok) {
                const err = await patchRes.json().catch(() => ({}));
                alert("Error updating task: " + (err.detail || patchRes.statusText));
                return;
            }

            // Reload table (and schedule gets regenerated server-side)
            await loadTasks();
        } catch (e) {
            console.error(e);
            alert(e.message);
        }
    });

    // ==========================================
    // 4. SCHEDULE GENERATION
    // ==========================================
    const scheduleSection = document.getElementById("Schedule");
    
    // Bind the "Generate Schedule" button inside #Tasks section
    document.querySelector(".generate-btn").addEventListener("click", async (e) => {
        e.preventDefault(); // Stop anchor jump for a moment
        scheduleSection.innerHTML = "<h2>Generating Schedule...</h2>";
        
        try {
            // Trigger Algorithm
            const genRes = await authFetch(`${API_URL}/api/scheduler/generate`, { method: "POST" });
            if(!genRes.ok) throw new Error("Generation failed");
            
            // Fetch Result
            const schedRes = await authFetch(`${API_URL}/api/scheduler/my-schedule`);
            const blocks = await schedRes.json();
            
            renderSchedule(blocks);
            
            // Smooth scroll
            document.getElementById("Schedule").scrollIntoView({ behavior: 'smooth' });
        } catch(e) {
            scheduleSection.innerHTML = `<h2>Error: ${e.message}</h2>`;
        }
    });

    function renderSchedule(blocks) {
      if (blocks.length === 0) {
          scheduleSection.innerHTML = "<h2>No schedule generated. Add tasks and availability!</h2>";
          return;
      }

      let html = `
          <h2>Your Optimized Plan</h2>
          <div class="task-card">
              <div class="schedule-grid" style="display: flex; flex-direction: column; gap: 10px; margin-top: 10px;">
      `;

      blocks.forEach(block => {
          const start = new Date(block.scheduled_start);
          const end = new Date(block.scheduled_end);

          // --- TIMEZONE FIX FOR REASONING TEXT ---
          let reasonDisplay = block.reasoning || 'Scheduled Task';
          
          // Regex to find "Deadline: YYYY-MM-DD HH:MM" (which is in UTC)
          reasonDisplay = reasonDisplay.replace(
              /Deadline: (\d{4}-\d{2}-\d{2} \d{2}:\d{2})/, 
              (match, dateStr) => {
                  // Append 'Z' to force JS to treat it as UTC, then convert to Local
                  const localDate = new Date(dateStr + "Z"); 
                  // Returns something like "2025. 12. 6. 5:03 AM"
                  return "Deadline: " + localDate.toLocaleString([], {
                      year: 'numeric', month: 'numeric', day: 'numeric', 
                      hour: '2-digit', minute:'2-digit'
                  });
              }
          );

          html += `
              <div class="tool-card" style="margin-top:0; padding: 15px;">
                  <h3 style="margin:0; color:#79d9ff;">
                      ${start.toLocaleDateString()} &bull;
                      ${start.toLocaleTimeString([], { hour:'2-digit', minute:'2-digit' })} -
                      ${end.toLocaleTimeString([], { hour:'2-digit', minute:'2-digit' })}
                  </h3>
                  <p style="margin: 5px 0 0 0;">${reasonDisplay}</p>
              </div>
          `;
      });

      html += `
              </div>
          </div>
      `;

      scheduleSection.innerHTML = html;
    }

    // ==========================================
    // 5. MUTUAL FREE TIME (Feature 5)
    // ==========================================
    const friendSelect = document.querySelector(".friend-select.long-select");
    const mutualDisplay = document.querySelector(".mutual-display");

    async function loadFriends() {
        try {
            // Fetch friends list
            const res = await authFetch(`${API_URL}/v2/users/${currentUserId}/friends/`);
            if(res.ok) {
                const friends = await res.json();
                friendSelect.innerHTML = '<option value="">Select a friend</option>';
                friends.forEach(f => {
                    const opt = document.createElement("option");
                    opt.value = f.id;
                    opt.textContent = f.name;
                    friendSelect.appendChild(opt);
                });
            }
        } catch(e) { console.error("Error loading friends", e); }
    }

    friendSelect.addEventListener("change", async () => {
        const friendId = friendSelect.value;
        if(!friendId) return;

        mutualDisplay.innerHTML = "<p class='subtle-text'>Calculating overlap...</p>";

        // Calculate Next 7 Days range
        const now = new Date();
        const nextWeek = new Date();
        nextWeek.setDate(now.getDate() + 7);

        try {
            const payload = {
                user_ids: [currentUserId, parseInt(friendId)],
                start_date: now.toISOString(),
                end_date: nextWeek.toISOString(),
                min_duration_minutes: 5
            };

            const res = await authFetch(`${API_URL}/v2/schedule/find-common-time`, {
                method: "POST",
                body: JSON.stringify(payload)
            });

            const data = await res.json();
            
            if(data.common_free_times.length === 0) {
                mutualDisplay.innerHTML = "<p class='subtle-text'>No mutual free time found in the next 7 days.</p>";
            } else {
                let html = "<ul style='padding-left: 20px; margin: 0;'>";
                data.common_free_times.slice(0, 5).forEach(slot => {
                    const start = new Date(slot.start);
                    const end = new Date(slot.end);
                    html += `<li><strong>${start.toDateString()}</strong>: ${start.toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'})} - ${end.toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'})} (${slot.duration_minutes} min)</li>`;
                });
                html += "</ul>";
                mutualDisplay.innerHTML = html;
            }

        } catch(e) {
            mutualDisplay.textContent = "Error finding time.";
        }
    });

    // ==========================================
    // 6. STUDY TIMER & ANALYTICS
    // ==========================================
    const timerSelect = document.getElementById("timerTaskSelect");
    const timerDisplay = document.getElementById("timerDisplay");
    let timerInterval = null;

    function updateTimerDropdown(tasks) {
        // Get the element dynamically to ensure it exists
        const dropdown = document.getElementById("timerTaskSelect");
        if (!dropdown) return;

        // Don't interrupt if the timer is currently counting down
        if (timerInterval) return; 

        // Save the currently selected value (if any) so we don't reset the user's choice annoyingly
        const currentValue = dropdown.value;

        // Rebuild options
        dropdown.innerHTML = '<option value="">Select a task to study</option>';
        tasks.forEach(t => {
            const opt = document.createElement("option");
            opt.value = t.id; // Task UUID
            opt.textContent = t.name;
            dropdown.appendChild(opt);
        });

        // Restore selection if it still exists
        if (currentValue) {
            dropdown.value = currentValue;
        }
    }

    async function checkActiveSession() {
        try {
            const res = await authFetch(`${API_URL}/api/study-timer/sessions/active`);
            const data = await res.json();
            
            if (data.active_session) {
                const sess = data.active_session;
                // Restore UI state
                timerSelect.value = sess.task_id;
                timerSelect.disabled = true;
                
                // Start local counter synced with server start time
                const startTime = new Date(sess.start_time).getTime();
                
                startLocalTimer(startTime);
            }
        } catch(e) { console.error(e); }
    }

    function startLocalTimer(startTimeMs) {
        clearInterval(timerInterval);
        timerInterval = setInterval(() => {
            const now = Date.now();
            const diff = Math.floor((now - startTimeMs) / 1000);
            
            const hrs = String(Math.floor(diff / 3600)).padStart(2, "0");
            const mins = String(Math.floor((diff % 3600) / 60)).padStart(2, "0");
            const secs = String(diff % 60).padStart(2, "0");
            timerDisplay.textContent = `${hrs}:${mins}:${secs}`;
        }, 1000);
    }

    document.getElementById("startTimer").addEventListener("click", async () => {
        const taskId = timerSelect.value;
        if(!taskId) { alert("Select a task first"); return; }

        try {
            const res = await authFetch(`${API_URL}/api/study-timer/sessions/start`, {
                method: "POST",
                body: JSON.stringify({ task_id: taskId })
            });

            if(res.ok) {
                const data = await res.json();
                timerSelect.disabled = true;
                startLocalTimer(new Date(data.start_time).getTime());
            } else {
                alert((await res.json()).detail);
            }
        } catch(e) { alert("Error starting timer"); }
    });

    document.getElementById("stopTimer").addEventListener("click", async () => {
        if(!timerInterval && timerDisplay.textContent === "00:00:00") return;

        try {
            const res = await authFetch(`${API_URL}/api/study-timer/sessions/stop`, { method: "POST" });
            if(res.ok) {
                clearInterval(timerInterval);
                timerInterval = null;
                timerDisplay.textContent = "00:00:00";
                timerSelect.disabled = false;
                alert("Session saved!");
                loadAnalytics(); // Refresh analytics
            }
        } catch(e) { alert("Error stopping timer"); }
    });

    // ==========================================
    // 7. AVAILABILITY MANAGEMENT
    // ==========================================
    const availList = document.getElementById("availability-list");

    async function loadAvailability() {
        try {
            const res = await authFetch(`${API_URL}/api/scheduler/availability`);
            if (res.ok) {
                const slots = await res.json();
                renderAvailability(slots);
            }
        } catch (e) {
            console.error("Error loading availability", e);
            availList.innerHTML = "<div class='subtle-text'>Error loading slots.</div>";
        }
    }

    function renderAvailability(slots) {
        availList.innerHTML = "";
        if (slots.length === 0) {
            availList.innerHTML = "<div class='subtle-text'>No free slots set. You appear busy 24/7!</div>";
            return;
        }

        slots.forEach(slot => {
            const item = document.createElement("div");
            item.className = "friend-item"; // Reuse existing style
            item.style.padding = "10px";
            item.innerHTML = `
                <span style="font-size: 14px; color: #e5e7eb;">
                    <strong>${slot.day_of_week}</strong>: ${slot.start_time} - ${slot.end_time}
                </span>
                <button class="tool-btn decline-btn" style="padding: 4px 10px; font-size: 12px;" onclick="deleteAvailability(${slot.id})">X</button>
            `;
            availList.appendChild(item);
        });
    }

    document.getElementById("btn-add-avail").addEventListener("click", async () => {
        const day = document.getElementById("avail-day").value;
        
        // FIX: Get the DOM Elements first, NOT the values yet
        const startEl = document.getElementById("avail-start");
        const endEl = document.getElementById("avail-end");

        // DEBUG: Check values correctly
        console.log("Start value:", startEl.value); 
        console.log("End value:", endEl.value);

        if (!startEl.value || !endEl.value) {
            alert("Please select both start and end times.");
            return;
        }
        
        const start = startEl.value;
        const end = endEl.value;

        // check duplicates / overlap
        const currentSlots = document.querySelectorAll("#availability-list .friend-item span");
        let hasOverlap = false;

        // Helper: Convert "HH:MM" to minutes from midnight
        const toMinutes = (timeStr) => {
            const [h, m] = timeStr.split(':').map(Number);
            return h * 60 + m;
        };

        const newStart = toMinutes(start);
        const newEnd = toMinutes(end);

        currentSlots.forEach(slot => {
            // Text format is: "Monday: 05:18 - 17:18"
            // We parse this text to compare values
            const text = slot.innerText; 
            const [slotDay, timeRange] = text.split(': '); // Split "Monday" from "05:18 - 17:18"
            
            if (slotDay.trim() === day) {
                const [sStr, eStr] = timeRange.split(' - ');
                const existingStart = toMinutes(sStr.trim());
                const existingEnd = toMinutes(eStr.trim());

                // Mathematical Overlap Check:
                // (StartA < EndB) AND (EndA > StartB)
                if (newStart < existingEnd && newEnd > existingStart) {
                    hasOverlap = true;
                }
            }
        });

        if (hasOverlap) {
            alert(`This time slot overlaps with an existing ${day} slot! Please remove the old one first.`);
            return; // STOP here
        }

        try {
            const res = await authFetch(`${API_URL}/api/scheduler/availability`, {
                method: "POST",
                body: JSON.stringify({
                    day_of_week: day,
                    start_time: start,
                    end_time: end
                })
            });

            if (res.ok) {
                loadAvailability(); // Refresh list
            } else {
                const err = await res.json();
                alert("Error: " + (err.detail || "Invalid time slot"));
            }
        } catch (e) {
            alert(e.message);
        }
    });

    // 8. Analytics
    async function loadAnalytics() {
        try {
            const res = await authFetch(`${API_URL}/api/study-timer/analytics`);
            const data = await res.json();

            // Total summary
            document.getElementById("totalHoursSummary").textContent =
            `Total hours (All time): ${data.summary.all_time.toFixed(2)} hours`;

            // Hours per task
            const taskSummary = document.getElementById("taskSummary");
            taskSummary.innerHTML = "";
            data.tasks.forEach(t => {
            taskSummary.innerHTML += `<div><strong>${t.task_name}</strong>: ${t.total_hours.toFixed(2)} hours</div>`;
            });

            // Breakdown by day
            const daySummary = document.getElementById("daySummary");
            daySummary.innerHTML = "";
            data.daily_breakdown.forEach(d => {
            daySummary.innerHTML += `<div><strong>${d.date}</strong>: ${d.hours.toFixed(2)} hours</div>`;
            });

        } catch (e) {
            console.error("Analytics error", e);
        }
    }

    // Initial Analytics load
    loadAnalytics();

    // ==========================================
    // 9. USER SETTINGS & AVATAR
    // ==========================================
    
    // Add this to your DOMContentLoaded event:
    // loadSettings();

    async function loadSettings() {
        console.log("Loading settings for User ID:", currentUserId); // Debug Log

        if (!currentUserId) {
            console.error("No User ID found. Cannot load profile.");
            return;
        }

        try {
            // 1. Get User Details
            const res = await authFetch(`${API_URL}/v2/users/${currentUserId}`);
            
            if (res.ok) {
                const data = await res.json();
                const user = data.user;

                console.log("User Data Loaded:", user); // Debug Log

                // Update UI
                const idEl = document.getElementById('settings-user-id');
                const nameEl = document.getElementById('settings-username');
                const emailEl = document.getElementById('settings-email');

                if (idEl) idEl.textContent = user.id;
                if (nameEl) nameEl.textContent = user.name;
                if (emailEl) emailEl.textContent = user.email;

                // 2. Check/Load Avatar
                loadAvatarImage(user.id);
            } else {
                console.error("Failed to fetch user data:", res.status);
            }
        } catch (e) {
            console.error("Error loading settings:", e);
        }
    }

    function loadAvatarImage(userId) {
        const img = document.getElementById('settings-avatar');
        // Add a timestamp to bypass browser caching when updating the image
        img.src = `${API_URL}/v2/users/${userId}/avatar?t=${new Date().getTime()}`;
        
        img.onerror = function() {
            // Fallback if no avatar exists
            this.src = "https://ui-avatars.com/api/?name=User&background=random"; 
        };
    }

    // --- Upload Avatar ---
    document.getElementById('avatar-upload').addEventListener('change', async (e) => {
        const file = e.target.files[0];
        if (!file) return;

        const formData = new FormData();
        formData.append('file', file);
        // Backend expects password or JWT. Since we use Bearer auth header in authFetch, 
        // we might need to adjust or pass a dummy password if the endpoint strictly requires form data.
        // Let's assume standard Bearer auth works for the endpoint based on your api.py.
        
        try {
            // Note: We use standard fetch here because authFetch forces JSON content-type
            // and FormData needs to set its own multipart boundary.
            const response = await fetch(`${API_URL}/v2/users/${currentUserId}/avatar`, {
                method: 'POST',
                headers: {
                    'Authorization': `Bearer ${token}`
                },
                body: formData
            });

            if (response.status === 409) {
                // If avatar exists, use PUT
                 await fetch(`${API_URL}/v2/users/${currentUserId}/avatar`, {
                    method: 'PUT',
                    headers: {
                        'Authorization': `Bearer ${token}`
                    },
                    body: formData
                });
            }

            // Refresh image
            loadAvatarImage(currentUserId);
            alert("Profile picture updated!");

        } catch (e) {
            console.error(e);
            alert("Upload failed.");
        }
    });

    // --- Delete Avatar ---
    document.getElementById('btn-delete-avatar').addEventListener('click', async () => {
        if(!confirm("Remove profile picture?")) return;

        try {
            const res = await authFetch(`${API_URL}/v2/users/${currentUserId}/avatar`, {
                method: 'DELETE'
            });
            if (res.ok) {
                loadAvatarImage(currentUserId);
                alert("Profile picture removed.");
            }
        } catch(e) {
            alert("Error removing avatar");
        }
    });

    // ==========================================
    // 10. FRIEND SYSTEM (Dynamic)
    // ==========================================
    const friendListEl = document.getElementById("friend-list-container");
    const requestListEl = document.getElementById("friend-requests-container");

    // --- Load Friends (For the List Card) ---
    async function loadFriendsList() {
        try {
            const res = await authFetch(`${API_URL}/v2/users/${currentUserId}/friends/`);
            if (res.ok) {
                const friends = await res.json();
                renderFriends(friends);
                // Also update the dropdown in Mutual Free Time (Feature 5)
                updateMutualDropdown(friends);
            }
        } catch (e) {
            console.error("Error loading friends", e);
            if(friendListEl) friendListEl.innerHTML = "<div class='subtle-text'>Error loading friends.</div>";
        }
    }

    function renderFriends(friends) {
        if (!friendListEl) return;
        friendListEl.innerHTML = "";
        if (friends.length === 0) {
            friendListEl.innerHTML = "<div class='subtle-text'>No friends yet. Add someone by ID below!</div>";
            return;
        }

        friends.forEach(f => {
            const item = document.createElement("div");
            item.className = "friend-item";
            
            // Avatar with Fallback
            const avatarUrl = `${API_URL}/v2/users/${f.id}/avatar?t=${new Date().getTime()}`;
            const fallbackUrl = `https://ui-avatars.com/api/?name=${f.name}&background=random&color=fff`;

            item.innerHTML = `
                <div style="display:flex; align-items:center; gap:12px;">
                    <img src="${avatarUrl}" 
                         onerror="this.onerror=null; this.src='${fallbackUrl}';" 
                         style="width:35px; height:35px; border-radius:50%; object-fit:cover; border: 1px solid rgba(255,255,255,0.2);">
                    
                    <div style="display:flex; flex-direction:column;">
                        <span class="friend-name" style="font-weight:600; font-size:14px;">${f.name}</span>
                        <span style="font-size:11px; color:#888;">ID: ${f.id}</span>
                    </div>
                </div>
                <div style="display:flex; gap:5px;">
                    <button class="tool-btn1 small-btn" style="background: #1f2933; border: 1px solid #79d9ff; color: #79d9ff;" onclick="viewFriendSchedule(${f.id}, '${f.name}')">View</button>
                    <button class="tool-btn1 small-btn decline-btn" onclick="removeFriend(${f.id}, '${f.name}')">Remove</button>
                </div>
            `;
            friendListEl.appendChild(item);
        });
    }

    // --- View Friend Schedule  ---
    window.viewFriendSchedule = async function(friendId, friendName) {
        const scheduleSection = document.getElementById("Schedule");
        scheduleSection.innerHTML = `<h2>Loading ${friendName}'s Schedule...</h2>`;
        scheduleSection.scrollIntoView({ behavior: 'smooth' });

        try {
            // Get dates for next 7 days
            const now = new Date();
            const nextWeek = new Date();
            nextWeek.setDate(now.getDate() + 7);

            const params = new URLSearchParams({
                start_date: now.toISOString(),
                end_date: nextWeek.toISOString()
            });

            // Note: This endpoint must exist in your backend. 
            // If it returns 404, check api.py for: @app.get("/v2/users/{user_id}/friends/{friend_id}/schedule/")
            const res = await authFetch(`${API_URL}/v2/users/${currentUserId}/friends/${friendId}/schedule/?${params}`);
            
            if (res.ok) {
                const entries = await res.json();
                renderFriendSchedule(entries, friendName);
            } else {
                const err = await res.json();
                scheduleSection.innerHTML = `<h2>Error loading schedule: ${err.detail || 'Unknown error'}</h2>`;
            }
        } catch (e) {
            console.error(e);
            scheduleSection.innerHTML = `<h2>Failed to load schedule.</h2>`;
        }
    };

    function renderFriendSchedule(entries, friendName) {
        const scheduleSection = document.getElementById("Schedule");
        
        // FIX 1: Wrap header in 'task-card' to match layout width (1100px) and padding
        let html = `
            <div class="task-card" style="margin-bottom: 20px; display: flex; justify-content: space-between; align-items: center; padding: 25px 30px;">
                <h2 style="margin:0; font-size: 24px;">${friendName}'s Schedule</h2>
                <button class="tool-btn1" onclick="restoreMySchedule()" style="margin:0;">Back to My Schedule</button>
            </div>
        `;

        if (entries.length === 0) {
            html += `
                <div class="task-card" style="text-align: center; padding: 40px;">
                    <p class="subtle-text">${friendName} has no scheduled tasks for this week.</p>
                </div>`;
            scheduleSection.innerHTML = html;
            return;
        }

        // Grid Container
        html += `<div class="task-card">
                    <div class="schedule-grid" style="display: grid; gap: 10px;">`;

        entries.forEach(entry => {
            const start = new Date(entry.start_time);
            const end = new Date(entry.end_time);
            
            const dateStr = start.toLocaleDateString();
            const timeStr = `${start.toLocaleTimeString([], { hour:'2-digit', minute:'2-digit' })} - ${end.toLocaleTimeString([], { hour:'2-digit', minute:'2-digit' })}`;

            html += `
                <div class="tool-card" style="margin-top:0; padding: 15px; border-left: 4px solid #79d9ff;">
                    <h3 style="margin:0; color:#79d9ff; font-size:16px;">
                        ${dateStr} &bull; ${timeStr}
                    </h3>
                    <p style="margin: 5px 0 0 0; color:#e5e7eb; font-weight: 500;">
                        Task: ${entry.title}
                    </p>
                    ${entry.reasoning ? `<p style="margin: 3px 0 0 0; font-size: 12px; color: #888;">${entry.reasoning.split('|')[0]}</p>` : ''}
                </div>
            `;
        });

        html += `   </div>
                 </div>`;
        
        scheduleSection.innerHTML = html;
    }

    window.restoreMySchedule = function() {
        document.getElementById("Schedule").innerHTML = `<h2>Select "Generate Schedule" to view your plan.</h2>`;
    };

    // --- Load Requests ---
    async function loadFriendRequests() {
        try {
            // q=incoming means requests sent TO me
            const res = await authFetch(`${API_URL}/v2/users/${currentUserId}/friend-requests/?q=incoming`);
            if (res.ok) {
                const requests = await res.json();
                renderRequests(requests);
            }
        } catch (e) {
            console.error("Error loading requests", e);
            if(requestListEl) requestListEl.innerHTML = "<div class='subtle-text'>Error loading requests.</div>";
        }
    }

    async function renderRequests(requests) {
        if (!requestListEl) return;
        requestListEl.innerHTML = "";
        if (requests.length === 0) {
            requestListEl.innerHTML = "<div class='subtle-text'>No pending requests.</div>";
            return;
        }

        for (const req of requests) {
            const senderId = req.from; 
            let senderName = `User ${senderId}`;
            
            try {
                const uRes = await authFetch(`${API_URL}/v2/users/${senderId}`);
                if(uRes.ok) {
                    const uData = await uRes.json();
                    senderName = uData.user.name;
                }
            } catch(e) {}

            const item = document.createElement("div");
            item.className = "friend-item"; // Reusing friend-item style for layout
            item.innerHTML = `
                <span class="friend-name" style="font-size:14px;">${senderName}</span>
                <div class="request-buttons">
                    <button class="tool-btn1 small-btn" onclick="acceptRequest(${senderId})">Accept</button>
                    <button class="tool-btn1 small-btn decline-btn" onclick="declineRequest(${senderId})">Decline</button>
                </div>
            `;
            requestListEl.appendChild(item);
        }
    }

    // --- Actions ---

    // 1) Send Request
    const btnSendReq = document.getElementById("btn-send-request");
    if(btnSendReq) {
        btnSendReq.addEventListener("click", async () => {
            const targetId = document.getElementById("add-friend-id").value;
            if (!targetId) return;

            if (targetId == currentUserId) {
                alert("You cannot add yourself!");
                return;
            }

            try {
                const formData = new URLSearchParams();
                formData.append('to_user_id', targetId);

                const res = await authFetch(`${API_URL}/v2/users/${currentUserId}/friend-requests/`, {
                    method: "POST",
                    headers: {
                        'Content-Type': 'application/x-www-form-urlencoded',
                        'Authorization': `Bearer ${token}`
                    },
                    body: formData
                });

                if (res.ok) {
                    alert("Friend request sent!");
                    document.getElementById("add-friend-id").value = "";
                } else {
                    const err = await res.json();
                    alert("Error: " + (err.detail || "Could not send request"));
                }
            } catch (e) {
                alert("Failed to send request");
            }
        });
    }

    // 2) Accept Request
    window.acceptRequest = async function(senderId) {
        try {
            const res = await authFetch(`${API_URL}/v2/users/${currentUserId}/friend-requests/${senderId}`, {
                method: "PUT"
            });
            if (res.ok) {
                loadFriendRequests(); 
                loadFriendsList();    
            }
        } catch (e) { alert("Error accepting request"); }
    };

    // 3) Decline Request
    window.declineRequest = async function(senderId) {
        if(!confirm("Decline this request?")) return;
        try {
            const res = await authFetch(`${API_URL}/v2/users/${currentUserId}/friend-requests/${senderId}`, {
                method: "DELETE"
            });
            if (res.ok) {
                loadFriendRequests();
            }
        } catch (e) { alert("Error declining request"); }
    };

    // 4) Remove Friend
    window.removeFriend = async function(friendId, name) {
        if(!confirm(`Remove ${name} from friends?`)) return;
        try {
            const res = await authFetch(`${API_URL}/v2/users/${currentUserId}/friends/${friendId}`, {
                method: "DELETE"
            });
            if (res.ok) {
                loadFriendsList();
            }
        } catch (e) { alert("Error removing friend"); }
    };

    // Helper for Mutual Dropdown
    function updateMutualDropdown(friends) {
        const select = document.querySelector(".friend-select.long-select");
        if(select) {
            select.innerHTML = '<option value="">Select a friend</option>';
            friends.forEach(f => {
                const opt = document.createElement("option");
                opt.value = f.id;
                opt.textContent = f.name;
                select.appendChild(opt);
            });
        }
    }

    // ==========================================
    // 11. CALENDAR EXPORT
    // ==========================================
    
    // --- Google Calendar Button ---
    // Since we are skipping OAuth for the demo, we download the file 
    // and instruct the user to import it manually.
    const btnGoogle = document.getElementById("btn-export-google");
    if (btnGoogle) {
    btnGoogle.addEventListener("click", async () => {
        try {
        const res = await authFetch(`${API_URL}/api/calendar/export/ics`);
        if (res.ok) {
            const blob = await res.blob();
            const url = window.URL.createObjectURL(blob);

            const a = document.createElement("a");
            a.href = url;
            a.download = "google_import.ics";
            document.body.appendChild(a);
            a.click();
            a.remove();
            window.URL.revokeObjectURL(url);

            alert(
            "Schedule file downloaded!\n\nTo finish exporting to Google:\n" +
            "1. Open Google Calendar\n2. Settings → Import & Export\n3. Import 'google_import.ics'"
            );
        } else {
            alert("No schedule data to export. Please 'Generate Schedule' first!");
        }
        } catch (e) {
        console.error(e);
        alert("Export failed.");
        }
    });
    }

    // --- Apple / Outlook Button ---
    const btnApple = document.getElementById("btn-export-apple");
    if (btnApple) {
    btnApple.addEventListener("click", async () => {
        try {
        const res = await authFetch(`${API_URL}/api/calendar/export/ics`);
        if (res.ok) {
            const blob = await res.blob();
            const url = window.URL.createObjectURL(blob);

            const a = document.createElement("a");
            a.href = url;
            a.download = "smart_schedule.ics";
            document.body.appendChild(a);
            a.click();
            a.remove();
            window.URL.revokeObjectURL(url);
        } else {
            alert("No schedule data to export. Please 'Generate Schedule' first!");
        }
        } catch (e) {
        console.error(e);
        alert("Export failed.");
        }
    });
    }

    // ==========================================
    // 12. AUTO-REFRESH (Safe Polling)
    // ==========================================
    
    function startAutoRefresh() {
        // Run every 10 seconds (10000 ms)
        setInterval(() => {
            // Only poll if logged in
            if (!localStorage.getItem('token')) return;

            // 1. Refresh Friends & Requests (Silent background update)
            loadFriendRequests();
            loadFriendsList();

            // 2. Refresh Mutual Time (If a friend is selected)
            const friendSelect = document.querySelector(".friend-select.long-select");
            const friendId = friendSelect ? friendSelect.value : null;
            
            // Only trigger calculation if a friend is currently selected
            if (friendId) {
                // Trigger the 'change' event manually to run the calculation logic again
                friendSelect.dispatchEvent(new Event('change'));
            }

        }, 10000); 
    }

    // ==========================================
    // 13. SYSTEM TELEMETRY (Connects to Event Service)
    // ==========================================
    function logSystemEvent(type) {
        if (!currentUserId) return;
        
        // Fire and forget (don't wait for response)
        fetch(`${API_URL}/v2/events/`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                when: new Date().toISOString(),
                source: "frontend_dashboard",
                type: type,
                payload: { "browser": navigator.userAgent },
                user: String(currentUserId) // Backend expects string
            })
        }).catch(err => console.log("Telemetry skipped"));
    }

    // Start the timer
    startAutoRefresh();

    window.deleteAvailability = async function(id) {
        if (!confirm("Remove this time slot?")) return;
        try {
            const res = await authFetch(`${API_URL}/api/scheduler/availability/${id}`, {
                method: "DELETE"
            });
            if (res.ok) {
                loadAvailability();
            } else {
                alert("Failed to delete slot.");
            }
        } catch (e) {
            alert("Error deleting slot");
        }
    };