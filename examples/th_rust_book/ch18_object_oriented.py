"""Chapter 18: encapsulation, trait objects, and state-oriented design."""

from crabwalk import rust


# Rust Book sources (encapsulated data plus behavior, Listings 18-1 and 18-2):
# https://doc.rust-lang.org/book/ch18-01-what-is-oo.html#encapsulation-that-hides-implementation-details
#
# The fields are public in generated Rust today because the move-aware Python
# wrapper needs construction access, but callers in compiled code use methods to
# preserve the collection invariant. Each @rust.method helper becomes an inherent
# Rust method; its first ownership annotation chooses self, &self, or &mut self.
@rust.struct
class AveragedCollection:
    values: rust.Vec[rust.f64]
    total: rust.f64
    count: rust.f64
    average: rust.f64


@rust.method(AveragedCollection, name="add")
def averaged_add(collection: rust.Mut[AveragedCollection], value: rust.f64) -> None:
    collection.values.push(value)
    collection.total = collection.total + value
    collection.count = collection.count + 1.0
    collection.average = collection.total / collection.count


@rust.method(AveragedCollection, name="remove")
def averaged_remove(collection: rust.Mut[AveragedCollection]) -> rust.f64:
    removed: rust.f64 = collection.values.pop().expect("collection is empty")
    collection.total = collection.total - removed
    collection.count = collection.count - 1.0
    if collection.count == 0.0:
        collection.average = 0.0
    else:
        collection.average = collection.total / collection.count
    return removed


@rust.method(AveragedCollection, name="average")
def averaged_value(collection: rust.Ref[AveragedCollection]) -> rust.f64:
    return collection.average


@rust.fn
def averaged_collection_demo() -> rust.f64:
    collection: AveragedCollection = AveragedCollection(
        values=rust.Vec([]),
        total=0.0,
        count=0.0,
        average=0.0,
    )
    collection.add(10.0)
    collection.add(20.0)
    collection.add(30.0)
    collection.remove()
    return collection.average()


# Rust Book sources (Draw, Screen, Button, SelectBox, Listings 18-3 through 18-10):
# https://doc.rust-lang.org/book/ch18-02-trait-objects.html
#
# This declaration emits a real Rust trait. `rust.impl` attaches implementations
# to unrelated concrete structs, while `rust.Dyn[Draw]` denotes `dyn Draw` and
# `rust.dyn_box` performs the checked unsizing coercion to Box<dyn Draw>.
Draw = rust.trait("Draw", draw=rust.u64)


@rust.struct
class Button:
    width: rust.u64
    height: rust.u64
    label: rust.String


@rust.struct
class SelectBox:
    width: rust.u64
    height: rust.u64
    option_count: rust.u64


@rust.impl(Draw, Button, name="draw")
def draw_button(button: rust.Ref[Button]) -> rust.u64:
    # Numeric output makes dispatch observable without requiring a GUI backend.
    return button.width * button.height


@rust.impl(Draw, SelectBox, name="draw")
def draw_select_box(select_box: rust.Ref[SelectBox]) -> rust.u64:
    return select_box.width * select_box.height + select_box.option_count


@rust.fn
def screen_draw_total() -> rust.u64:
    # One Vec holds two concrete types. `iter_ref` yields borrowed trait-object
    # boxes, and component.draw() dispatches through each object's vtable.
    components: rust.Vec[rust.Box[rust.Dyn[Draw]]] = rust.Vec(
        [
            rust.dyn_box(
                Draw,
                SelectBox(width=75, height=10, option_count=3),
            ),
            rust.dyn_box(
                Draw,
                Button(width=50, height=10, label="OK"),
            ),
        ]
    )
    total: rust.u64 = 0
    for component in components.iter_ref():
        total += component.draw()
    return total


# Rust Book source (the object-oriented state pattern, Listings 18-11 to 18-18):
# https://doc.rust-lang.org/book/ch18-03-oo-design-patterns.html#attempting-traditional-object-oriented-style
#
# The Draw example above demonstrates the chapter's dynamic-dispatch machinery.
# For the blog workflow, the Book ultimately recommends moving state into types;
# the runnable adaptation below goes directly to that stronger final design.


# Rust Book sources (states encoded as types, Listings 18-19 through 18-21):
# https://doc.rust-lang.org/book/ch18-03-oo-design-patterns.html#encoding-states-and-behavior-as-types
#
# DraftPost has no content() method, PendingReviewPost has no add_text() method,
# and only PublishedPost exposes content(). Invalid transitions therefore fail in
# rustc instead of becoming runtime branches. Consuming method receivers (`self`)
# ensure an old state cannot remain usable after a transition.
@rust.struct
class DraftPost:
    content: rust.String


@rust.struct
class PendingReviewPost:
    content: rust.String


@rust.struct
class PublishedPost:
    content: rust.String


@rust.method(DraftPost, name="add_text")
def draft_add_text(draft: rust.Mut[DraftPost], text: rust.Str) -> None:
    draft.content.push_str(text)


@rust.method(DraftPost, name="request_review")
def draft_request_review(draft: rust.Owned[DraftPost]) -> PendingReviewPost:
    return PendingReviewPost(content=draft.content)


@rust.method(PendingReviewPost, name="approve")
def pending_approve(pending: rust.Owned[PendingReviewPost]) -> PublishedPost:
    return PublishedPost(content=pending.content)


@rust.method(PublishedPost, name="content")
def published_content(post: rust.Ref[PublishedPost]) -> rust.String:
    return post.content


@rust.fn
def publish_post() -> rust.String:
    draft: DraftPost = DraftPost(content="")
    draft.add_text("I ate a salad for lunch today")
    pending: PendingReviewPost = draft.request_review()
    published: PublishedPost = pending.approve()
    return published.content()


# Rust Book source (chapter summary and the tradeoff between dispatch and types):
# https://doc.rust-lang.org/book/ch18-03-oo-design-patterns.html#summary
#
# Inspecting this module's generated Rust shows both choices side by side:
# `Box<dyn Draw>` performs dynamic dispatch, while the three post structs use
# static dispatch and encode their legal transition graph in concrete types.
