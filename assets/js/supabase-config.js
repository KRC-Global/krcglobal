/**
 * Supabase 클라이언트 초기화
 *
 * 사용 전 아래 값을 Supabase 프로젝트 대시보드에서 확인하여 설정하세요:
 * - SUPABASE_URL: Settings > API > Project URL
 * - SUPABASE_ANON_KEY: Settings > API > anon/public key
 */

const SUPABASE_URL = 'https://zzypdvwdwgwocczpaaiu.supabase.co';
const SUPABASE_ANON_KEY = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Inp6eXBkdndkd2d3b2NjenBhYWl1Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzU1MDU5NDMsImV4cCI6MjA5MTA4MTk0M30.SYyjgllxiqCiw1n1xD3aoQ5kjmFlOMh2jeyXGRnIVcQ';

window.supabaseClient = supabase.createClient(SUPABASE_URL, SUPABASE_ANON_KEY);
