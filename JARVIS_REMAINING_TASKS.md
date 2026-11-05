# JARVIS REMAINING TASKS

Date: 2026-11-01  
Based on: Complete Repository Audit  
Priority: Critical → High → Medium → Low  

---

## CRITICAL (Must Address Before Production)

### C1. Runtime Validation & Testing
- [ ] **Install dependencies and run tests** - `requirements.txt` exists but packages not installed; 89 test files need validation
- [ ] **Verify backend startup** - Test `uvicorn main:app` can start with minimal config
- [ ] **Health/Ready endpoints** - Validate `/health` and `/ready` respond correctly
- [ ] **Bootstrap validation** - Ensure all services initialize without errors in clean environment
- [ ] **Dependency resolution** - Check for missing/compatible package versions

### C2. Security Hardening
- [ ] **Review secret management** - Ensure no secrets in codebase (scanned, looks clean but verify)
- [ ] **Validate auth flows** - Test owner login, token validation, session revocation
- [ ] **Telegram webhook security** - Verify owner-only enforcement works
- [ ] **NVIDIA endpoint security** - Confirm fail-closed behavior
- [ ] **Log sanitization** - Verify all sensitive data redacted
- [ ] **CORS configuration** - Review allowed origins for production

### C3. Environment Configuration
- [ ] **Create production .env** - Based on `.env.example`, configure all required vars
- [ ] **MongoDB setup** - Configure and test connection if using persistent storage
- [ ] **API keys** - Obtain and configure necessary provider keys
- [ ] **Telegram bot** - Configure bot token and allowed user ID
- [ ] **Signing secrets** - Generate secure `ARIA_APP_TOKEN_SECRET` (32+ chars)

---

## HIGH PRIORITY

### H1. AI Provider Integration
- [ ] **Integrate NVIDIA into LLM Router** - Currently only separate endpoint; add to main routing
- [ ] **Test provider fallbacks** - Verify circuit breakers and cooldowns work
- [ ] **Validate model configurations** - Check default models are accessible
- [ ] **Local model support** - Test Ollama integration for codegen if used

### H2. Knowledge System
- [ ] **Initialize knowledge corpus** - Run ingestion if needed
- [ ] **Test vector search** - Verify ChromaDB collections work
- [ ] **Knowledge refresh** - Test idle knowledge acquisition
- [ ] **Graph building** - Validate knowledge graph construction

### H3. Memory & Persistence
- [ ] **MongoDB collections** - Ensure all required collections exist
- [ ] **Data migrations** - Check if any migrations needed
- [ ] **Memory consolidation** - Test experience engine
- [ ] **Conversation persistence** - Verify cross-session memory

### H4. Autonomous Systems
- [ ] **Self-engineering subsystem** - Test Phase 1 components (repository intelligence, etc.)
- [ ] **Approval gates** - Verify Telegram approval flow
- [ ] **Deployment safety** - Ensure production deploys blocked by default
- [ ] **Autonomous learning** - Test reflection and consolidation jobs

### H5. Integrations
- [ ] **Google integrations** - Test Gmail/Calendar/Drive OAuth flows
- [ ] **GitHub integration** - Test repo operations
- [ ] **Briefing system** - Test alert collection and digests
- [ ] **Durable job queue** - Test with MongoDB

---

## MEDIUM PRIORITY

### M1. Android Application
- [ ] **Build verification** - Test Android build in Android Studio
- [ ] **API connectivity** - Verify app connects to backend
- [ ] **Auth flow** - Test login from Android app
- [ ] **Branding** - Confirm JARVIS branding applied
- [ ] **Backward compatibility** - Verify with existing installs

### M2. Performance & Optimization
- [ ] **Bootstrap time** - Optimize massive bootstrap if slow
- [ ] **Memory usage** - Monitor large in-memory structures
- [ ] **Query optimization** - Review MongoDB/ChromaDB queries
- [ ] **Background jobs** - Tune scheduler intervals

### M3. Monitoring & Observability
- [ ] **Logging** - Ensure structured logging works
- [ ] **Metrics** - Add/verify health metrics
- [ ] **Error tracking** - Consider error reporting
- [ ] **API monitoring** - Test api_monitor.py

### M4. Code Quality
- [ ] **Reduce complexity** - Consider refactoring large files (cognitive_core, bootstrap)
- [ ] **Type hints** - Improve type coverage
- [ ] **Documentation** - Update inline docs where needed
- [ ] **Dead code** - Identify and remove unused code

---

## LOW PRIORITY

### L1. Features
- [ ] **Multimodal enhancements** - Vision/voice improvements
- [ ] **Additional skills/actions** - Extend capabilities
- [ ] **UI improvements** - If web UI exists
- [ ] **Localization** - If needed

### L2. Maintenance
- [ ] **Dependency updates** - Review and update packages
- [ ] **Security patches** - Monitor dependencies
- [ ] **Cleanup** - Remove temporary files, old artifacts
- [ ] **Archive old reports** - Organize documentation

---

## Notes

- Many features are implemented but **untested in this environment**
- The system is very complex - changes should be incremental and tested
- Autonomous engineering features are powerful but need careful validation
- NVIDIA integration exists as separate endpoint but not in main router
- Strict no-LLM mode is default (good for safety)
- All changes must wait for approval
