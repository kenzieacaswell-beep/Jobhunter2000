export type Job={id:number;title:string;company_name:string;location:string;source_url:string;description:string;combined_score:number;rule_score:number;ai_score:number|null;ai_status:string;review_status:string;salary_min:number|null;salary_max:number|null;first_seen_at:string;posted_at?:string;work_arrangement?:string;dismiss_reason?:string;eligible:number;eligibility_reason?:string;match_tier:'strong'|'good'|'stretch'|'low'|'excluded';rule_result?:any;ai_result?:any;application_stage?:string};
export type Application={id:number;job_id:number;stage:string;notes:string;next_follow_up?:string;title:string;company_name:string;location:string;source_url:string;combined_score:number;updated_at:string};
export type Company={id:number;name:string;ats_type:string;token:string;enabled:number;last_success_at?:string;last_error?:string;list_sources?:string;shortlist_reason?:string;active_jobs?:number;matching_jobs?:number};

export class ApiError extends Error { constructor(public status:number,message:string){super(message)} }
export async function api<T>(path:string,options:RequestInit={}) : Promise<T> {
 const response=await fetch(`/api${path}`,{headers:{...(options.body instanceof FormData?{}:{'Content-Type':'application/json'}),...(options.headers||{})},...options});
 if(!response.ok){let message='Something went wrong. Please try again.';try{const data=await response.json();message=data.detail||data.message||message}catch{message=await response.text()||message}throw new ApiError(response.status,message)}
 return response.json() as Promise<T>;
}
export const stages=['Preparing','Applied','Recruiter Screen','Interviewing','Offer','Rejected','Withdrawn'];
