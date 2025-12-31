-- BAS Workflow Steps Table Migration
-- Run this manually to create the workflow steps table

-- Create the workflow steps table
CREATE TABLE IF NOT EXISTS bas_workflow_steps (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    bas_statement_id UUID NOT NULL,
    client_id VARCHAR(36) NOT NULL,
    
    -- Step info
    step_type VARCHAR(20) NOT NULL,  -- prepare, review, approve, lodge
    step_order INTEGER NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    
    -- Assigned user
    assigned_to VARCHAR(36),
    assigned_to_email VARCHAR(255),
    assigned_to_role VARCHAR(50),
    assigned_at TIMESTAMP WITH TIME ZONE,
    
    -- Completion info
    completed_by VARCHAR(36),
    completed_by_email VARCHAR(255),
    completed_at TIMESTAMP WITH TIME ZONE,
    
    -- Rejection info
    rejected_by VARCHAR(36),
    rejected_by_email VARCHAR(255),
    rejected_at TIMESTAMP WITH TIME ZONE,
    rejection_reason TEXT,
    
    -- Notes
    notes TEXT,
    
    -- Due date
    due_date TIMESTAMP WITH TIME ZONE,
    
    -- Timestamps
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Create indexes
CREATE INDEX IF NOT EXISTS idx_bas_workflow_steps_bas_id ON bas_workflow_steps(bas_statement_id);
CREATE INDEX IF NOT EXISTS idx_bas_workflow_steps_client_id ON bas_workflow_steps(client_id);
CREATE INDEX IF NOT EXISTS idx_bas_workflow_steps_status ON bas_workflow_steps(status);
CREATE INDEX IF NOT EXISTS idx_bas_workflow_steps_assigned_to ON bas_workflow_steps(assigned_to);

-- Add workflow_status column to bas_statements if not exists
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'bas_statements' AND column_name = 'workflow_status'
    ) THEN
        ALTER TABLE bas_statements ADD COLUMN workflow_status VARCHAR(20) DEFAULT 'draft';
    END IF;
END $$;

-- Add current_workflow_step column to bas_statements if not exists
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'bas_statements' AND column_name = 'current_workflow_step'
    ) THEN
        ALTER TABLE bas_statements ADD COLUMN current_workflow_step VARCHAR(20) DEFAULT NULL;
    END IF;
END $$;

-- Comment
COMMENT ON TABLE bas_workflow_steps IS 'BAS multi-step sign-off workflow tracking';
COMMENT ON COLUMN bas_workflow_steps.step_type IS 'Workflow step: prepare, review, approve, lodge';
COMMENT ON COLUMN bas_workflow_steps.status IS 'Step status: pending, in_progress, completed, rejected, skipped';
