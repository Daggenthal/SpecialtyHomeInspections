// Sends www.specialtyhomeinspections.biz (any page) to the same page on the bare address.
// Deployed by the editor's Publish together with the website, only once the real address is attached.
export default {
  fetch(request, env) {
    const url = new URL(request.url);
    url.hostname = env.APEX || url.hostname.replace(/^www\./, "");
    url.protocol = "https:";
    return Response.redirect(url.toString(), 301);
  },
};
