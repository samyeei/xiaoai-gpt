export class ConversationLease{
 owner=null;token=null;
 acquire(owner){if(this.owner!==null)return null;this.owner=owner;return this.token=Symbol(owner);}
 release(owner,token){if(this.owner!==owner||this.token!==token)return false;this.owner=null;this.token=null;return true;}
}
