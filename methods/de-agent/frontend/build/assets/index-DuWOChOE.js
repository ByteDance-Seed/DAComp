import{r as c}from"./chunk-ZYFC6VSF-CV8XXl5-.js";let T={data:""},F=e=>typeof window=="object"?((e?e.querySelector("#_goober"):window._goober)||Object.assign((e||document.head).appendChild(document.createElement("style")),{innerHTML:" ",id:"_goober"})).firstChild:e||T,_=/(?:([\u0080-\uFFFF\w-%@]+) *:? *([^{;]+?);|([^;}{]*?) *{)|(}\s*)/g,H=/\/\*[^]*?\*\/|  +/g,z=/\n+/g,b=(e,t)=>{let r="",i="",n="";for(let a in e){let o=e[a];a[0]=="@"?a[1]=="i"?r=a+" "+o+";":i+=a[1]=="f"?b(o,a):a+"{"+b(o,a[1]=="k"?"":t)+"}":typeof o=="object"?i+=b(o,t?t.replace(/([^,])+/g,s=>a.replace(/([^,]*:\S+\([^)]*\))|([^,])+/g,l=>/&/.test(l)?l.replace(/&/g,s):s?s+" "+l:l)):a):o!=null&&(a=/^--/.test(a)?a:a.replace(/[A-Z]/g,"-$&").toLowerCase(),n+=b.p?b.p(a,o):a+":"+o+";")}return r+(t&&n?t+"{"+n+"}":n)+i},y={},P=e=>{if(typeof e=="object"){let t="";for(let r in e)t+=r+P(e[r]);return t}return e},L=(e,t,r,i,n)=>{let a=P(e),o=y[a]||(y[a]=(l=>{let d=0,p=11;for(;d<l.length;)p=101*p+l.charCodeAt(d++)>>>0;return"go"+p})(a));if(!y[o]){let l=a!==e?e:(d=>{let p,f,m=[{}];for(;p=_.exec(d.replace(H,""));)p[4]?m.shift():p[3]?(f=p[3].replace(z," ").trim(),m.unshift(m[0][f]=m[0][f]||{})):m[0][p[1]]=p[2].replace(z," ").trim();return m[0]})(e);y[o]=b(n?{["@keyframes "+o]:l}:l,r?"":"."+o)}let s=r&&y.g?y.g:null;return r&&(y.g=y[o]),((l,d,p,f)=>{f?d.data=d.data.replace(f,l):d.data.indexOf(l)===-1&&(d.data=p?l+d.data:d.data+l)})(y[o],t,i,s),o},R=(e,t,r)=>e.reduce((i,n,a)=>{let o=t[a];if(o&&o.call){let s=o(r),l=s&&s.props&&s.props.className||/^go/.test(s)&&s;o=l?"."+l:s&&typeof s=="object"?s.props?"":b(s,""):s===!1?"":s}return i+n+(o??"")},"");function j(e){let t=this||{},r=e.call?e(t.p):e;return L(r.unshift?r.raw?R(r,[].slice.call(arguments,1),t.p):r.reduce((i,n)=>Object.assign(i,n&&n.call?n(t.p):n),{}):r,F(t.target),t.g,t.o,t.k)}let I,A,N;j.bind({g:1});let h=j.bind({k:1});function U(e,t,r,i){b.p=t,I=e,A=r,N=i}function v(e,t){let r=this||{};return function(){let i=arguments;function n(a,o){let s=Object.assign({},a),l=s.className||n.className;r.p=Object.assign({theme:A&&A()},s),r.o=/ *go\d+/.test(l),s.className=j.apply(r,i)+(l?" "+l:"");let d=e;return e[0]&&(d=s.as||e,delete s.as),N&&d[0]&&N(s),I(d,s)}return n}}var V=e=>typeof e=="function",O=(e,t)=>V(e)?e(t):e,q=(()=>{let e=0;return()=>(++e).toString()})(),S=(()=>{let e;return()=>{if(e===void 0&&typeof window<"u"){let t=matchMedia("(prefers-reduced-motion: reduce)");e=!t||t.matches}return e}})(),Y=20,M=(e,t)=>{switch(t.type){case 0:return{...e,toasts:[t.toast,...e.toasts].slice(0,Y)};case 1:return{...e,toasts:e.toasts.map(a=>a.id===t.toast.id?{...a,...t.toast}:a)};case 2:let{toast:r}=t;return M(e,{type:e.toasts.find(a=>a.id===r.id)?1:0,toast:r});case 3:let{toastId:i}=t;return{...e,toasts:e.toasts.map(a=>a.id===i||i===void 0?{...a,dismissed:!0,visible:!1}:a)};case 4:return t.toastId===void 0?{...e,toasts:[]}:{...e,toasts:e.toasts.filter(a=>a.id!==t.toastId)};case 5:return{...e,pausedAt:t.time};case 6:let n=t.time-(e.pausedAt||0);return{...e,pausedAt:void 0,toasts:e.toasts.map(a=>({...a,pauseDuration:a.pauseDuration+n}))}}},D=[],x={toasts:[],pausedAt:void 0},w=e=>{x=M(x,e),D.forEach(t=>{t(x)})},Z={blank:4e3,error:4e3,success:2e3,loading:1/0,custom:4e3},B=(e={})=>{let[t,r]=c.useState(x),i=c.useRef(x);c.useEffect(()=>(i.current!==x&&r(x),D.push(r),()=>{let a=D.indexOf(r);a>-1&&D.splice(a,1)}),[]);let n=t.toasts.map(a=>{var o,s,l;return{...e,...e[a.type],...a,removeDelay:a.removeDelay||((o=e[a.type])==null?void 0:o.removeDelay)||e?.removeDelay,duration:a.duration||((s=e[a.type])==null?void 0:s.duration)||e?.duration||Z[a.type],style:{...e.style,...(l=e[a.type])==null?void 0:l.style,...a.style}}});return{...t,toasts:n}},J=(e,t="blank",r)=>({createdAt:Date.now(),visible:!0,dismissed:!1,type:t,ariaProps:{role:"status","aria-live":"polite"},message:e,pauseDuration:0,...r,id:r?.id||q()}),$=e=>(t,r)=>{let i=J(t,e,r);return w({type:2,toast:i}),i.id},u=(e,t)=>$("blank")(e,t);u.error=$("error");u.success=$("success");u.loading=$("loading");u.custom=$("custom");u.dismiss=e=>{w({type:3,toastId:e})};u.remove=e=>w({type:4,toastId:e});u.promise=(e,t,r)=>{let i=u.loading(t.loading,{...r,...r?.loading});return typeof e=="function"&&(e=e()),e.then(n=>{let a=t.success?O(t.success,n):void 0;return a?u.success(a,{id:i,...r,...r?.success}):u.dismiss(i),n}).catch(n=>{let a=t.error?O(t.error,n):void 0;a?u.error(a,{id:i,...r,...r?.error}):u.dismiss(i)}),e};var K=(e,t)=>{w({type:1,toast:{id:e,height:t}})},W=()=>{w({type:5,time:Date.now()})},E=new Map,X=1e3,G=(e,t=X)=>{if(E.has(e))return;let r=setTimeout(()=>{E.delete(e),w({type:4,toastId:e})},t);E.set(e,r)},Q=e=>{let{toasts:t,pausedAt:r}=B(e);c.useEffect(()=>{if(r)return;let a=Date.now(),o=t.map(s=>{if(s.duration===1/0)return;let l=(s.duration||0)+s.pauseDuration-(a-s.createdAt);if(l<0){s.visible&&u.dismiss(s.id);return}return setTimeout(()=>u.dismiss(s.id),l)});return()=>{o.forEach(s=>s&&clearTimeout(s))}},[t,r]);let i=c.useCallback(()=>{r&&w({type:6,time:Date.now()})},[r]),n=c.useCallback((a,o)=>{let{reverseOrder:s=!1,gutter:l=8,defaultPosition:d}=o||{},p=t.filter(g=>(g.position||d)===(a.position||d)&&g.height),f=p.findIndex(g=>g.id===a.id),m=p.filter((g,C)=>C<f&&g.visible).length;return p.filter(g=>g.visible).slice(...s?[m+1]:[0,m]).reduce((g,C)=>g+(C.height||0)+l,0)},[t]);return c.useEffect(()=>{t.forEach(a=>{if(a.dismissed)G(a.id,a.removeDelay);else{let o=E.get(a.id);o&&(clearTimeout(o),E.delete(a.id))}})},[t]),{toasts:t,handlers:{updateHeight:K,startPause:W,endPause:i,calculateOffset:n}}},ee=h`
from {
  transform: scale(0) rotate(45deg);
	opacity: 0;
}
to {
 transform: scale(1) rotate(45deg);
  opacity: 1;
}`,te=h`
from {
  transform: scale(0);
  opacity: 0;
}
to {
  transform: scale(1);
  opacity: 1;
}`,ae=h`
from {
  transform: scale(0) rotate(90deg);
	opacity: 0;
}
to {
  transform: scale(1) rotate(90deg);
	opacity: 1;
}`,re=v("div")`
  width: 20px;
  opacity: 0;
  height: 20px;
  border-radius: 10px;
  background: ${e=>e.primary||"#ff4b4b"};
  position: relative;
  transform: rotate(45deg);

  animation: ${ee} 0.3s cubic-bezier(0.175, 0.885, 0.32, 1.275)
    forwards;
  animation-delay: 100ms;

  &:after,
  &:before {
    content: '';
    animation: ${te} 0.15s ease-out forwards;
    animation-delay: 150ms;
    position: absolute;
    border-radius: 3px;
    opacity: 0;
    background: ${e=>e.secondary||"#fff"};
    bottom: 9px;
    left: 4px;
    height: 2px;
    width: 12px;
  }

  &:before {
    animation: ${ae} 0.15s ease-out forwards;
    animation-delay: 180ms;
    transform: rotate(90deg);
  }
`,se=h`
  from {
    transform: rotate(0deg);
  }
  to {
    transform: rotate(360deg);
  }
`,ie=v("div")`
  width: 12px;
  height: 12px;
  box-sizing: border-box;
  border: 2px solid;
  border-radius: 100%;
  border-color: ${e=>e.secondary||"#e0e0e0"};
  border-right-color: ${e=>e.primary||"#616161"};
  animation: ${se} 1s linear infinite;
`,oe=h`
from {
  transform: scale(0) rotate(45deg);
	opacity: 0;
}
to {
  transform: scale(1) rotate(45deg);
	opacity: 1;
}`,ne=h`
0% {
	height: 0;
	width: 0;
	opacity: 0;
}
40% {
  height: 0;
	width: 6px;
	opacity: 1;
}
100% {
  opacity: 1;
  height: 10px;
}`,le=v("div")`
  width: 20px;
  opacity: 0;
  height: 20px;
  border-radius: 10px;
  background: ${e=>e.primary||"#61d345"};
  position: relative;
  transform: rotate(45deg);

  animation: ${oe} 0.3s cubic-bezier(0.175, 0.885, 0.32, 1.275)
    forwards;
  animation-delay: 100ms;
  &:after {
    content: '';
    box-sizing: border-box;
    animation: ${ne} 0.2s ease-out forwards;
    opacity: 0;
    animation-delay: 200ms;
    position: absolute;
    border-right: 2px solid;
    border-bottom: 2px solid;
    border-color: ${e=>e.secondary||"#fff"};
    bottom: 6px;
    left: 6px;
    height: 10px;
    width: 6px;
  }
`,de=v("div")`
  position: absolute;
`,ce=v("div")`
  position: relative;
  display: flex;
  justify-content: center;
  align-items: center;
  min-width: 20px;
  min-height: 20px;
`,pe=h`
from {
  transform: scale(0.6);
  opacity: 0.4;
}
to {
  transform: scale(1);
  opacity: 1;
}`,ue=v("div")`
  position: relative;
  transform: scale(0.6);
  opacity: 0.4;
  min-width: 20px;
  animation: ${pe} 0.3s 0.12s cubic-bezier(0.175, 0.885, 0.32, 1.275)
    forwards;
`,me=({toast:e})=>{let{icon:t,type:r,iconTheme:i}=e;return t!==void 0?typeof t=="string"?c.createElement(ue,null,t):t:r==="blank"?null:c.createElement(ce,null,c.createElement(ie,{...i}),r!=="loading"&&c.createElement(de,null,r==="error"?c.createElement(re,{...i}):c.createElement(le,{...i})))},fe=e=>`
0% {transform: translate3d(0,${e*-200}%,0) scale(.6); opacity:.5;}
100% {transform: translate3d(0,0,0) scale(1); opacity:1;}
`,ge=e=>`
0% {transform: translate3d(0,0,-1px) scale(1); opacity:1;}
100% {transform: translate3d(0,${e*-150}%,-1px) scale(.6); opacity:0;}
`,ye="0%{opacity:0;} 100%{opacity:1;}",he="0%{opacity:1;} 100%{opacity:0;}",be=v("div")`
  display: flex;
  align-items: center;
  background: #fff;
  color: #363636;
  line-height: 1.3;
  will-change: transform;
  box-shadow: 0 3px 10px rgba(0, 0, 0, 0.1), 0 3px 3px rgba(0, 0, 0, 0.05);
  max-width: 350px;
  pointer-events: auto;
  padding: 8px 10px;
  border-radius: 8px;
`,ve=v("div")`
  display: flex;
  justify-content: center;
  margin: 4px 10px;
  color: inherit;
  flex: 1 1 auto;
  white-space: pre-line;
`,xe=(e,t)=>{let r=e.includes("top")?1:-1,[i,n]=S()?[ye,he]:[fe(r),ge(r)];return{animation:t?`${h(i)} 0.35s cubic-bezier(.21,1.02,.73,1) forwards`:`${h(n)} 0.4s forwards cubic-bezier(.06,.71,.55,1)`}},we=c.memo(({toast:e,position:t,style:r,children:i})=>{let n=e.height?xe(e.position||t||"top-center",e.visible):{opacity:0},a=c.createElement(me,{toast:e}),o=c.createElement(ve,{...e.ariaProps},O(e.message,e));return c.createElement(be,{className:e.className,style:{...n,...r,...e.style}},typeof i=="function"?i({icon:a,message:o}):c.createElement(c.Fragment,null,a,o))});U(c.createElement);var Ee=({id:e,className:t,style:r,onHeightUpdate:i,children:n})=>{let a=c.useCallback(o=>{if(o){let s=()=>{let l=o.getBoundingClientRect().height;i(e,l)};s(),new MutationObserver(s).observe(o,{subtree:!0,childList:!0,characterData:!0})}},[e,i]);return c.createElement("div",{ref:a,className:t,style:r},n)},$e=(e,t)=>{let r=e.includes("top"),i=r?{top:0}:{bottom:0},n=e.includes("center")?{justifyContent:"center"}:e.includes("right")?{justifyContent:"flex-end"}:{};return{left:0,right:0,display:"flex",position:"absolute",transition:S()?void 0:"all 230ms cubic-bezier(.21,1.02,.73,1)",transform:`translateY(${t*(r?1:-1)}px)`,...i,...n}},ke=j`
  z-index: 9999;
  > * {
    pointer-events: auto;
  }
`,k=16,Oe=({reverseOrder:e,position:t="top-center",toastOptions:r,gutter:i,children:n,containerStyle:a,containerClassName:o})=>{let{toasts:s,handlers:l}=Q(r);return c.createElement("div",{id:"_rht_toaster",style:{position:"fixed",zIndex:9999,top:k,left:k,right:k,bottom:k,pointerEvents:"none",...a},className:o,onMouseEnter:l.startPause,onMouseLeave:l.endPause},s.map(d=>{let p=d.position||t,f=l.calculateOffset(d,{reverseOrder:e,gutter:i,defaultPosition:t}),m=$e(p,f);return c.createElement(Ee,{id:d.id,key:d.id,onHeightUpdate:l.updateHeight,className:d.visible?ke:"",style:m},d.type==="custom"?O(d.message,d):n?n(d):c.createElement(we,{toast:d,position:p}))}))},je=u;export{Oe as O,je as V};
