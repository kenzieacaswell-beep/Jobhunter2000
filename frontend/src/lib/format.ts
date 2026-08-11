export const money=(value:number|null|undefined)=>value==null?'Compensation unknown':new Intl.NumberFormat('en-US',{style:'currency',currency:'USD',maximumFractionDigits:0}).format(value);
export const relative=(value?:string)=>{if(!value)return 'Recently';const days=Math.max(0,Math.floor((Date.now()-new Date(value).getTime())/86400000));return days===0?'Today':days===1?'Yesterday':`${days} days ago`};
export const initials=(value:string)=>value.split(/\s+/).slice(0,2).map(x=>x[0]).join('').toUpperCase();
