import { afterEach, expect, it, vi } from "vitest";
import { portfolioWorkspace, portfolioRequest } from "./portfolio-client";

afterEach(()=>vi.unstubAllGlobals());
it("distinguishes an absent real account from an empty calculated portfolio",async()=>{
 const response={state:"unavailable",capture:null,cycles:[],risk:null,records:[],audit:[],issues:["No account capture"]};
 vi.stubGlobal("fetch",vi.fn().mockResolvedValue(new Response(JSON.stringify(response))));
 const result=await portfolioWorkspace("moomoo","17");
 expect(result.risk).toBeNull();
 expect(result.state).toBe("unavailable");
});
it("rejects numeric coercion and malformed financial results",async()=>{
 const response={state:"available",capture:null,cycles:[{cycle:{cycle_id:"x"},realized_net:999}],risk:null,records:[],audit:[],issues:[]};
 vi.stubGlobal("fetch",vi.fn().mockResolvedValue(new Response(JSON.stringify(response))));
 await expect(portfolioWorkspace("moomoo","17")).rejects.toThrow("incompatible");
});
it("shows the sanitized account gateway error without loading demo data",async()=>{
 const fetcher=vi.fn().mockResolvedValue(new Response(JSON.stringify({message:"Start official OpenD"}),{status:503}));
 vi.stubGlobal("fetch",fetcher);
 await expect(portfolioRequest("/discover",{})).rejects.toThrow("Start official OpenD");
 expect(fetcher).toHaveBeenCalledTimes(1);
});
