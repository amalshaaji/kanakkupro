from django.db import migrations


FORWARD = """
CREATE FUNCTION sales_invoice_guard() RETURNS trigger AS $$
BEGIN
    IF TG_OP IN ('UPDATE', 'DELETE') AND OLD.state = 'issued' THEN
        RAISE EXCEPTION 'issued documents are immutable' USING ERRCODE = '23514';
    END IF;
    IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
    IF TG_OP = 'UPDATE' AND NEW.tenant_id <> OLD.tenant_id THEN
        RAISE EXCEPTION 'invoice tenant cannot change' USING ERRCODE = '23514';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM customers_customer WHERE id = NEW.customer_id AND tenant_id = NEW.tenant_id) THEN
        RAISE EXCEPTION 'invoice customer tenant mismatch' USING ERRCODE = '23514';
    END IF;
    IF NEW.parent_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM sales_invoice WHERE id = NEW.parent_id AND tenant_id = NEW.tenant_id
          AND state = 'issued' AND kind = 'invoice' AND customer_id = NEW.customer_id
    ) THEN
        RAISE EXCEPTION 'correction invoice tenant mismatch' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END; $$ LANGUAGE plpgsql;
CREATE TRIGGER sales_invoice_guard BEFORE INSERT OR UPDATE OR DELETE ON sales_invoice
FOR EACH ROW EXECUTE FUNCTION sales_invoice_guard();

CREATE FUNCTION sales_line_guard() RETURNS trigger AS $$
DECLARE parent_state text; parent_tenant uuid;
BEGIN
    IF TG_OP IN ('UPDATE', 'DELETE') THEN
        SELECT state INTO parent_state FROM sales_invoice WHERE id = OLD.invoice_id FOR UPDATE;
        IF parent_state = 'issued' THEN
            RAISE EXCEPTION 'issued lines are immutable' USING ERRCODE = '23514';
        END IF;
    END IF;
    IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
    SELECT state, tenant_id INTO parent_state, parent_tenant FROM sales_invoice WHERE id = NEW.invoice_id FOR UPDATE;
    IF parent_state <> 'draft' OR parent_tenant <> NEW.tenant_id THEN
        RAISE EXCEPTION 'line parent is issued or belongs to another tenant' USING ERRCODE = '23514';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM catalog_catalogitem WHERE id = NEW.item_id AND tenant_id = NEW.tenant_id) THEN
        RAISE EXCEPTION 'line catalog tenant mismatch' USING ERRCODE = '23514';
    END IF;
    IF NEW.source_line_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM sales_invoiceline l JOIN sales_invoice i ON i.id=l.invoice_id
        WHERE l.id=NEW.source_line_id AND l.tenant_id=NEW.tenant_id AND i.state='issued'
    ) THEN
        RAISE EXCEPTION 'credit source tenant mismatch' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END; $$ LANGUAGE plpgsql;
CREATE TRIGGER sales_line_guard BEFORE INSERT OR UPDATE OR DELETE ON sales_invoiceline
FOR EACH ROW EXECUTE FUNCTION sales_line_guard();

CREATE FUNCTION financial_append_only() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'financial ledger entries are append-only' USING ERRCODE = '23514';
END; $$ LANGUAGE plpgsql;
CREATE TRIGGER payment_append_only BEFORE UPDATE OR DELETE ON payments_payment
FOR EACH ROW EXECUTE FUNCTION financial_append_only();
CREATE TRIGGER reversal_append_only BEFORE UPDATE OR DELETE ON payments_paymentreversal
FOR EACH ROW EXECUTE FUNCTION financial_append_only();
CREATE TRIGGER command_append_only BEFORE UPDATE OR DELETE ON sales_financialcommand
FOR EACH ROW EXECUTE FUNCTION financial_append_only();

CREATE FUNCTION payments_scope_guard() RETURNS trigger AS $$
DECLARE document sales_invoice%ROWTYPE; balance numeric;
BEGIN
    SELECT * INTO document FROM sales_invoice WHERE id=NEW.invoice_id FOR UPDATE;
    IF document.tenant_id <> NEW.tenant_id OR document.state <> 'issued' OR document.kind <> 'invoice' THEN
        RAISE EXCEPTION 'payment invoice scope mismatch' USING ERRCODE = '23514';
    END IF;
    IF TG_TABLE_NAME = 'payments_paymentreversal' THEN
        IF NOT EXISTS (SELECT 1 FROM payments_payment WHERE id=NEW.payment_id
            AND tenant_id=NEW.tenant_id AND invoice_id=NEW.invoice_id) THEN
            RAISE EXCEPTION 'reversal payment scope mismatch' USING ERRCODE = '23514';
        END IF;
    ELSE
        IF document.currency <> NEW.currency THEN
            RAISE EXCEPTION 'payment currency mismatch' USING ERRCODE = '23514';
        END IF;
        SELECT document.total + COALESCE((SELECT SUM(CASE WHEN kind='credit_note' THEN -total ELSE total END)
            FROM sales_invoice WHERE parent_id=document.id AND state='issued'),0)
            - COALESCE((SELECT SUM(p.amount) FROM payments_payment p
            WHERE p.invoice_id=document.id AND NOT EXISTS (
                SELECT 1 FROM payments_paymentreversal r WHERE r.payment_id=p.id)),0) INTO balance;
        IF NEW.amount > balance THEN
            RAISE EXCEPTION 'payment exceeds balance' USING ERRCODE = '23514';
        END IF;
    END IF;
    RETURN NEW;
END; $$ LANGUAGE plpgsql;
CREATE TRIGGER payment_scope BEFORE INSERT ON payments_payment FOR EACH ROW EXECUTE FUNCTION payments_scope_guard();
CREATE TRIGGER reversal_scope BEFORE INSERT ON payments_paymentreversal FOR EACH ROW EXECUTE FUNCTION payments_scope_guard();

CREATE FUNCTION financial_owner_guard() RETURNS trigger AS $$
BEGIN
    IF NEW.tenant_id <> OLD.tenant_id THEN
        RAISE EXCEPTION 'business record ownership cannot change' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END; $$ LANGUAGE plpgsql;
CREATE TRIGGER customer_owner_guard BEFORE UPDATE ON customers_customer FOR EACH ROW EXECUTE FUNCTION financial_owner_guard();
CREATE TRIGGER catalog_owner_guard BEFORE UPDATE ON catalog_catalogitem FOR EACH ROW EXECUTE FUNCTION financial_owner_guard();
"""

REVERSE = """
DROP TRIGGER catalog_owner_guard ON catalog_catalogitem;
DROP TRIGGER customer_owner_guard ON customers_customer;
DROP FUNCTION financial_owner_guard();
DROP TRIGGER reversal_scope ON payments_paymentreversal;
DROP TRIGGER payment_scope ON payments_payment;
DROP FUNCTION payments_scope_guard();
DROP TRIGGER command_append_only ON sales_financialcommand;
DROP TRIGGER reversal_append_only ON payments_paymentreversal;
DROP TRIGGER payment_append_only ON payments_payment;
DROP FUNCTION financial_append_only();
DROP TRIGGER sales_line_guard ON sales_invoiceline;
DROP FUNCTION sales_line_guard();
DROP TRIGGER sales_invoice_guard ON sales_invoice;
DROP FUNCTION sales_invoice_guard();
"""


class Migration(migrations.Migration):
    dependencies = [("sales", "0001_initial"), ("payments", "0002_initial")]
    operations = [migrations.RunSQL(FORWARD, REVERSE)]
